"""
Skill Executor — Skill execution engine (main workflow)
"""

import json
import os
import traceback
from typing import Any, Dict, Optional

from app.framework.model.llm import llm_call
from app.framework.data.data_fetcher import FetchAbortError, fetch_all_data
from app.skill_explore.input_parser import ParsedInput
from app.skill_explore.skill_md_manager import SkillDoc
from app.util.logger import business_log, error_log, info_log

# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def execute_skill(
    skill: SkillDoc,
    parsed_input: ParsedInput
) -> Dict[str, Any]:
    """
    Execute Skill full workflow
    """
    request_id = parsed_input.request_id
    _SEP = "-" * 50
    info_log(f"\n{_SEP}\n Skill execution started\n skill=[{skill.name}]  scene=[{parsed_input.scene_id}]  request_id=[{request_id}]\n Pipeline: Step3.1 Fetch Data → Step3.2 Build Prompt → Step3.3 LLM Inference → Step3.4 Post-process\n{_SEP}")

    try:
        early = _step0_pre_check(parsed_input)
        if early is not None:
            info_log(f"[Step0] Pre-check matched, returning early")
            return early

        info_log(f"\n{_SEP}\n [Step 3.1] Fetch Data & Knowledge\n{_SEP}")
        fetched_data = _step1_fetch_data(skill, parsed_input)
        # TODO: Current knowledge retrieval is based on a local mock file.
        # Replace get_knowledge() in get_knowlege.py with your real knowledge base query
        # (e.g., vector search, RAG retrieval) to inject domain-specific context into the prompt.
        knowledge = _step1_fetch_knowledge(skill, parsed_input)

        info_log(f"\n{_SEP}\n [Step 3.2] Build Prompt\n{_SEP}")
        final_prompt = _step2_build_prompt(skill, fetched_data, knowledge, parsed_input)

        info_log(f"\n{_SEP}\n [Step 3.3] LLM Inference\n{_SEP}")
        raw_output = _step3_llm_infer(final_prompt, request_id, parsed_input)

        info_log(f"\n{_SEP}\n [Step 3.4] Post-process\n{_SEP}")
        result = _step4_post_process(
            raw_output=raw_output,
            parsed_input=parsed_input,
            request_id=request_id,
            fetched_data=fetched_data,
        )

        info_log(f"\n{_SEP}\n Skill execution done — conclusion=[{result['conclusion']}]\n{_SEP}")
        return result

    except FetchAbortError as e:
        error_log(f"skill_executor: [{request_id}] Step1 data fetch aborted: {e}")
        return _error_result(f"Data fetch failed: {e}", request_id)
    except Exception:
        error_log(f"skill_executor: [{request_id}] Unexpected exception\n" + traceback.format_exc())
        return _error_result("Skill execution error, please retry later", request_id)


# ─────────────────────────────────────────────────────────────────────────────
# Step 0 — Pre-check interception
# ─────────────────────────────────────────────────────────────────────────────

def _step0_pre_check(
    parsed_input: ParsedInput
) -> Optional[Dict[str, Any]]:
    """
    # Business can define custom pre-check rules here; supports skipping all subsequent steps.
    Returns None if no match found; main flow continues.
    """
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Fetch data and knowledge
# ─────────────────────────────────────────────────────────────────────────────

def _step1_fetch_data(
    skill: SkillDoc,
    parsed_input: ParsedInput,
):
    """Fetch all data sources and knowledge content in parallel based on SkillDoc.load_data_schema"""
    request_id = parsed_input.request_id
    info_log(f"[Step 3.1] Fetch data — schema entries={len(skill.load_data_schema)}")

    merged_data = fetch_all_data(skill, parsed_input)
    # Add data and knowledge demo content

    info_log(f"[Step 3.1] Data fetched — types={list(merged_data.keys())}")
    return merged_data

def _step1_fetch_knowledge(
    skill: SkillDoc,
    parsed_input: ParsedInput,
):
    from app.framework.knowledge.get_knowlege import get_knowledge

    request_id = parsed_input.request_id
    info_log(f"[Step 3.1] Knowledge lookup")

    service_name = parsed_input.context.get("service_name", "")
    knowledge_data = get_knowledge(service_name=service_name)

    info_log(f"[Step 3.1] Knowledge fetched")
    return knowledge_data

# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Build Prompt
# ─────────────────────────────────────────────────────────────────────────────

def _step2_build_prompt(
    skill: SkillDoc,
    fetched_data: Dict[str, Any],
    knowledge: str,
    parsed_input: ParsedInput,
) -> str:
    """Merge SkillDoc.prompt template with fetched data to generate the final prompt string for LLM.

    Assembly strategy:
        1. Use skill.prompt as base text
        2. Append serialized content of each data source after the ## 输入数据 placeholder
        3. If prompt has no ## 输入数据 placeholder, append data block at the end

    Returns:
        Final prompt string
    """
    request_id = parsed_input.request_id
    info_log(f"[Step 3.2] Building prompt")

    base_prompt = skill.prompt

    data_block_lines: list[Any] = []
    data_block_lines.append(f"## Input Knowledge:\n{knowledge}")
    for type_key, data in fetched_data.items():
        if data is None:
            continue
        if isinstance(data, str):
            data_str = data
        else:
            data_str = json.dumps(data, ensure_ascii=False, indent=2)
        data_block_lines.append(f"### {type_key}\n{data_str}")

    data_block = "\n\n".join(data_block_lines)

    # Inject into ## 输入数据 placeholder section
    input_data_placeholder = "## 输入数据"
    if input_data_placeholder in base_prompt:
        final_prompt = base_prompt.replace(
            input_data_placeholder,
            f"{input_data_placeholder}\n\n{data_block}" if data_block else input_data_placeholder,
        )
    else:
        final_prompt = base_prompt + ("\n\n## 输入数据\n\n" + data_block if data_block else "")

    info_log(f"[Step 3.2] Prompt ready — length={len(final_prompt)}")
    return final_prompt


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — LLM Inference
# ─────────────────────────────────────────────────────────────────────────────

def _step3_llm_infer(final_prompt: str, request_id: str, parsed_input: ParsedInput) -> str:
    """
    Call LLM, return raw string output.

    Fallback strategy:
        - On call failure or empty string, return fallback string without raising exception
    """
    info_log(f"[Step 3.3] Calling LLM...")

    raw_output = llm_call(
        user_prompt=final_prompt,
        request_id=request_id,
    )

    if not raw_output:
        error_log(f"skill_executor: [{request_id}] LLM returned empty string, using fallback")
        raw_output = "LLM inference failed, unable to generate analysis conclusion"

    info_log(f"[Step 3.3] LLM done — output length={len(raw_output)}")
    return raw_output


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Post-process output
# ─────────────────────────────────────────────────────────────────────────────

def _step4_post_process(
    raw_output: str,
    parsed_input: ParsedInput,
    request_id: str,
    fetched_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Parse LLM raw output, build response_payload for return
    """
    info_log(f"[Step 3.4] Post-processing")

    # General LLM output parsing
    raw_conclusion, conclusion, output = _parse_llm_output(raw_output, request_id, parsed_input.source)

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"conclusion": conclusion, "output": output, "traceId": request_id},
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    info_log(f"[Step 3.4] Done")
    return {
        "payload": payload,
        "conclusion": raw_conclusion,
        "raw_output": raw_output,
        "success": True,
    }


def _render_value(value: Any, indent: int = 0) -> str:
    """
    Recursively render any JSON value as readable Markdown text.

    Rules:
        - str  → return as-is
        - list → prefix each item with "- " (recursively render list/dict sub-items)
        - dict → each key: value on its own line (recursively render value)
        - others → str() conversion
    """
    prefix = "  " * indent
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        lines = []
        for item in value:
            rendered = _render_value(item, indent + 1)
            # Multi-line item first line keeps "- ", continuation lines align indentation
            sub_lines = rendered.splitlines()
            if sub_lines:
                lines.append(f"{prefix}- {sub_lines[0]}")
                for sub in sub_lines[1:]:
                    lines.append(f"{prefix}  {sub}")
            else:
                lines.append(f"{prefix}-")
        return "\n".join(lines)
    if isinstance(value, dict):
        lines = []
        for idx, (k, v) in enumerate(value.items(), 1):
            rendered = _render_value(v, indent + 1)
            sub_lines = rendered.splitlines()
            if len(sub_lines) <= 1:
                lines.append(f"{prefix}- {idx}.{k}: {rendered}")
            else:
                lines.append(f"{prefix}- {idx}.{k}:")
                lines.extend(sub_lines)
        return "\n".join(lines)
    return str(value)


def _parse_llm_output(raw_output: str, request_id: str, source: str = ""):
    """General LLM output parsing function."""
    # ── Extract JSON text (compatible with <think> prefix) ──
    json_text = raw_output
    think_end = raw_output.find("</think>")
    if think_end != -1:
        json_text = raw_output[think_end + len("</think>"):].strip()

    try:
        parsed = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        info_log(f"skill_executor: [{request_id}] LLM output not JSON, using raw text fallback")
        return "Needs attention", raw_output, "None"

    # ── Extract conclusion (required field) ────────────────────────────────────
    raw_conclusion = parsed.get("conclusion", "Needs attention")
    summary = parsed.get("summary", "")

    # ── Build conclusion_text (main display text)───────────────────────────────
    lines = [f"**Conclusion**: **{raw_conclusion}**"]
    if summary:
        lines.append("")
        lines.append(summary)

    # Flatten all JSON fields except conclusion/summary/outputs for display
    skip_keys = {"conclusion", "summary", "outputs"}
    for key, value in parsed.items():
        if key in skip_keys:
            continue
        rendered = _render_value(value)
        sub_lines = rendered.splitlines()
        lines.append("")
        if len(sub_lines) <= 1:
            lines.append(f"**{key}**: {rendered}")
        else:
            lines.append(f"**{key}**:")
            lines.extend(sub_lines)
    conclusion_text = "\n".join(lines).rstrip()

    # ── Build output_text (iterate suggestions to concatenate string)──────────────────
    suggestions = parsed.get("suggestions", {})
    output_parts = []
    if isinstance(suggestions, dict):
        for key, items in suggestions.items():
            if not items:
                continue
            if isinstance(items, list):
                output_parts.append(f"**{key}**:\n" + "\n".join(f"- {item}" for item in items))
            else:
                output_parts.append(f"**{key}**: {items}")
    elif isinstance(suggestions, list):
        output_parts = [f"- {item}" for item in suggestions if item]
    output_text = "\n".join(output_parts) if output_parts else "None"

    info_log(
        f"skill_executor: [{request_id}] LLM output parsed "
        f"source={source} raw_conclusion={raw_conclusion!r}"
    )
    return raw_conclusion, conclusion_text, output_text



def _error_result(
    message: str,
    request_id: str
) -> Dict[str, Any]:
    """Build unified error return structure, compatible with existing response_payload format."""
    conclusion = "Needs attention"
    output = f"[Skill execution error] {message}"

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"conclusion": conclusion, "output": output, "traceId": request_id},
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    return {
        "payload": payload,
        "conclusion": conclusion,
        "raw_output": "",
        "success": False,
    }
