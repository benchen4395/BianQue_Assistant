import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from app.framework.conf.conf_manager import ConfManager, get_conf_manager
from app.framework.model.llm import llm_call
from app.skill_explore.input_parser import ParsedInput
from app.skill_explore.skill_md_manager import SkillDoc, SkillManager, skill_md_manager
from app.util.logger import info_log

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Absolute path to data_lake.yaml (capabilities used for type validation, still reads local)
_DATA_LAKE_PATH = os.path.join(os.path.dirname(__file__), "..", "framework", "data", "data_lake.yaml")

# skill_create scene config path (defines per-scene output JSON format spec)
# skill_create_scene_config.yaml deprecated; output format spec is embedded directly in _build_stage2_user_prompt

# Max retries on validation failure (total attempts = _MAX_RETRIES + 1)
_MAX_RETRIES = 3

# Alias for "default" business_id in Skill file (consistent with skill_search fallback logic)
_DEFAULT_BUSINESS_ALIAS = "normal"


# ─────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ─────────────────────────────────────────────────────────────────────────────

class SkillCreateError(Exception):
    """skill_create process failed (including retry exhaustion)"""


_STAGE1_SYSTEM_PROMPT = """\
你是一名运维 Skill 数据配置专家。
你的任务是：根据给定的运维告警/巡检场景描述，从「可用数据能力表」中选择**合适的数据源**用于问题分析，\
输出选择依据说明和 LoadDataSchema JSON。

【分析约束】
1. 你只能从「可用数据能力表」中选择数据源，不能凭空想象新的 type
2. 读取知识库能力为核心分析能力
3. 不要选择重复的指标
4. 跟当前业务相关的指标需要尽量包含

【输出格式 - 必须严格遵守，分两部分】
第一部分：全部数据源的选择依据写在 <reasoning> 标签内：
<reasoning>
这里写选择依据，可以是多行文字
</reasoning>

第二部分：紧接着输出 LoadDataSchema JSON 数组（不加任何代码块标记）：
[
  {
    "type": "...",
    "params_list": [...]
  }
]

【JSON 格式规范】
- 每条 entry 的 type 必须与数据能力表中的 type 字段完全一致，禁止自造 type
- 每个 entry 的 params_list 至少有一条记录，每条记录需包含：
    "name": "<用一句话描述这次调用的目的>"
    <其他该 type 支持的参数，按需填写；各 type 的参数约束和注意事项见「可用数据能力表」中对应条目的「说明」列>"""

_STAGE2_SYSTEM_PROMPT = """\
你是一名运维分析 Prompt 设计专家。
你的任务是：根据给定的运维场景和已确定的数据源 Schema，生成一段可直接用于 LLM 分析的高质量运维 Prompt。

【设计原则 - 生成 Prompt 时参考】
1. 知识库是核心能力：如果 LoadDataSchema 中包含 knowledge_base，必须作为"步骤1：历史反馈分析"排在最前，且明确规则：
   - customized_feedback 包含"忽略该服务" → 强制结论"不需要关注"，无需继续分析
   - customized_feedback 包含"结论不合理" → 将该反馈作为核心参考，参与后续分析判断
2. 分步决策，层层推进：知识库 → 其他数据源逐步分析 → 兜底分析
3. 指标分析要具体：对 tianwen_metric / inspect_service_data 类数据根据指标类型给出具体分析规则：
   - QPS/耗时：分析绝对值趋势和日环比/周同比波动，要求给出具体数值（如：QPS 从 100 增长到 2000）
   - CPU：关注日环比/周同比异常（如：当前 40%，日环比增加 20%）
   - 内存：仅当水位持续升高且高位运行（如持续 >80%）或呈明显上升趋势时才报异常；内存下降不算异常
   - rt（耗时）指标单位为微秒（μs），分析时必须换算为毫秒（÷1000）后再描述和判断
4. 曲线分析原则：
   - 判断异常必须基于**当天数据（today 数组）**的整段曲线趋势；l1d/l7d 仅作为历史对比参考
   - l1d/l7d 数组本身出现异常点，不作为报异常的依据；只有当天 today 数组出现异常才报
   - 不能因为单个孤立的异常点就判定异常；异常依据：today 数组连续多个点持续偏高/偏低，或整体趋势与 l1d/l7d 均值出现显著偏离
   - 若仅 today 曲线末尾最后 1-2 个点出现异常，需判断是否为正常的数据上报延迟，不应直接报异常
4. 事件类数据（coredump/oom/change_event/index_change）：分析事件与告警时间窗口的关联性，重叠或接近则标记关联
5. suggestions 字段：base_metric 含逐指标分析结论（含具体数值）；event 仅列出需要关注的事件项名称

【输出格式 - 必须严格遵守】
1. Prompt 中必须包含"## 输入数据"这一行作为数据注入占位符（该行后不要加任何内容）
2. Prompt 中必须包含"## 输出要求"部分，要求 LLM 以 JSON 格式输出分析结论。
   JSON 格式由你根据场景自行设计，但必须满足以下约束：
   - 必须包含 "conclusion" 字段，值为一句话总结（如"需要关注"/"不需要关注"/"异常"/"正常"等）
   - 必须包含 "summary" 字段，值为对本次分析的一句话摘要
   - 其余字段根据场景需要自由设计（如指标分析列表、事件列表、根因、建议等），字段名用英文
   - 所有字段名统一用英文，值可以是中文
   - 禁止输出 Markdown 代码块标记（```）
3. 直接输出 Prompt 文本，不要加代码块标记（```）或说明前缀"""

# Per-scene Stage2 System Prompt conf key prefix
# Full key format: bianque_stage2_prompt_{scene_id}
_STAGE2_PROMPT_CONF_KEY_PREFIX = "stage2_prompt_"


def _load_stage2_system_prompt(scene_id: str) -> str:
    """
    Load Stage2 system prompt by scene_id, priority:
      1. conf: key = bianque_stage2_prompt_{scene_id}
      2. Local file: workflow/stage2_prompt_{scene_id}.md
      3. Generic fallback: _STAGE2_SYSTEM_PROMPT (hardcoded constant)

    Unknown scene_id (e.g. future new scene) falls back to generic prompt without error.
    """
    key = f"{_STAGE2_PROMPT_CONF_KEY_PREFIX}{scene_id}"
    content = get_conf_manager().get_string(key)
    if content and content.strip():
        info_log(f"skill_create: stage2 prompt loaded from conf, scene_id={scene_id}, key={key}")
        return content.strip()

    info_log(f"skill_create: stage2 prompt using generic fallback, scene_id={scene_id}")
    return _STAGE2_SYSTEM_PROMPT


# ─────────────────────────────────────────────────────────────────────────────
# Data source loading
# ─────────────────────────────────────────────────────────────────────────────

def _load_valid_types(path: str = _DATA_LAKE_PATH) -> "set[str]":
    """
    Extract all valid types from data_lake.yaml capabilities, used for Stage1 validation.
    Raises SkillCreateError on load failure.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        caps = data.get("capabilities", [])
        types: "set[str]" = {cap["type"] for cap in caps if cap.get("type")}
        info_log(f"skill_create: loaded valid type set, {len(types)} entries: {sorted(types)}")
        return types
    except (OSError, yaml.YAMLError) as e:
        raise SkillCreateError(f"Failed to load data_lake.yaml: {e}") from e


def _load_summary_table() -> str:
    """
    Read data_lake_summary.md content from conf, used as data source decision reference for LLM.
    Raises SkillCreateError on read failure.
    """
    content = get_conf_manager().get_string(ConfManager.KEY_DATA_LAKE)
    if not content:
        raise SkillCreateError(
            f"Failed to load data_lake_summary: conf key [{ConfManager.KEY_DATA_LAKE}] is empty or missing"
        )
    return content


def _parse_metric_name_map() -> Dict[str, str]:
    """
    Read data_lake_summary.md from conf, parse "data name -> metric_name" mapping.
    Only parses tianwen_metric type rows where metric_name column is not '—'.

    Returns e.g.:
    {
        "CPU avg usage": "cpu.busy.usage",
        "Memory usage": "mem.usage",
        "QPS": "rpcmonitor.service.requests.qps / rpc.client.requests.qps",
        ...
    }
    """
    content = get_conf_manager().get_string(ConfManager.KEY_DATA_LAKE)
    if not content:
        raise SkillCreateError(
            f"Failed to load data_lake_summary: conf key [{ConfManager.KEY_DATA_LAKE}] is empty or missing"
        )

    result: Dict[str, str] = {}
    in_table = False
    header_parsed = False
    name_col = type_col = metric_col = -1

    for line in content.splitlines():
        stripped = line.strip()
        # HR separator signals end of main table
        if in_table and stripped == "---":
            break
        if not stripped.startswith("|"):
            continue

        cells = [c.strip().strip("`") for c in stripped.split("|") if c.strip()]

        if not in_table:
            # First table row as header
            in_table = True
            header_parsed = False
            for i, cell in enumerate(cells):
                if "数据名称" in cell:
                    name_col = i
                elif cell.lower() in ("type",):
                    type_col = i
                elif "metric_name" in cell.lower():
                    metric_col = i
            header_parsed = True
            continue

        # Skip separator row (---|---|...)
        if all(set(c) <= set("-") for c in cells if c):
            continue

        if not header_parsed or name_col < 0 or type_col < 0 or metric_col < 0:
            continue
        if len(cells) <= max(name_col, type_col, metric_col):
            continue

        data_name = cells[name_col]
        metric_val = cells[metric_col]
        # Skip rows without metric_name (value is — or empty)
        if not data_name or metric_val in ("-", "—", ""):
            continue

        result[data_name] = metric_val

    info_log(f"skill_create: parsed metric_name map, {len(result)} entries: {result}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Scene description construction
# ─────────────────────────────────────────────────────────────────────────────

def _build_scene_desc(parsed: ParsedInput) -> str:
    """Extract key scene info from ParsedInput and build scene description text for LLM."""
    lines = [
        f"场景类型: {parsed.scene_id}",
        f"业务标识: {parsed.biz_list}",
        f"触发来源: {parsed.source}",
    ]
    ctx = parsed.context
    for k, v in ctx.items():
        lines.append(f"{k}: {v}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Stage1: LoadDataSchema generation
# ─────────────────────────────────────────────────────────────────────────────

def _build_stage1_user_prompt(scene_desc: str, summary_table: str) -> str:
    """Build Stage1 user_prompt: scene description + summary table + format example."""
    return f"""【当前运维场景】
{scene_desc}

【可用数据能力表（表格列: 数据名称 | type | 说明 | metric_name | 限制）】
{summary_table}

【输出格式示例】（仅供格式参考，不要照抄内容）
[
  {{
    "type": "coredump_stack",
    "params_list": [
      {{
        "name": "获取服务 Coredump 堆栈"
      }}
    ]
  }},
  {{
    "type": "tianwen_metric",
    "params_list": [
      {{
        "name": "获取 OOM 计数指标",
        "metric_name": "sys.process.oom.count"
      }}
    ]
  }}
]

请根据上面的场景，输出 LoadDataSchema JSON（只输出 JSON，不带任何额外文字）："""


def _extract_stage1_parts(output: str) -> Tuple[str, str]:
    """
    Split Stage1 LLM output into reasoning and JSON parts.
    """
    import re
    reasoning = ""
    reasoning_match = re.search(r"<reasoning>(.*?)</reasoning>", output, re.DOTALL)
    if reasoning_match:
        reasoning = reasoning_match.group(1).strip()

    # JSON part: content after </reasoning>; if no tag, use full output
    if "</reasoning>" in output:
        json_part = output[output.index("</reasoning>") + len("</reasoning>"):].strip()
    else:
        json_part = output.strip()

    # Remove possible code block markers
    if json_part.startswith("```"):
        lines = json_part.splitlines()
        json_part = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()

    return reasoning, json_part


def _validate_stage1(output: str, valid_types: "set[str]") -> Tuple[bool, str]:
    """
    Validate Stage1 LLM output.
    """
    _, json_text = _extract_stage1_parts(output)
    
    info_log(f"skill_create: Stage1 output JSON text: {json_text}")

    try:
        schema = json.loads(json_text)
    except json.JSONDecodeError as e:
        return False, f"JSON parse failed: {e} (extracted JSON text: {json_text[:200]})"

    if not isinstance(schema, list):
        return False, "Output must be a JSON array"

    if len(schema) == 0:
        return False, "LoadDataSchema cannot be empty, select at least one data source"

    for entry in schema:
        t = entry.get("type", "")
        if not t:
            return False, "Entry missing type field"
        if t not in valid_types:
            return False, (
                f"type '{t}' not in available data capability list, "
                f"valid types: {sorted(valid_types)}"
            )
        params_list = entry.get("params_list")
        if not isinstance(params_list, list) or len(params_list) == 0:
            return False, f"type '{t}' params_list is empty or not an array"

    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Stage2: Prompt text generation
# ─────────────────────────────────────────────────────────────────────────────

def _build_stage2_user_prompt(scene_desc: str, schema_json: str) -> str:
    """Build Stage2 user_prompt: scene description + LoadDataSchema + format requirements."""
    return f"""【当前运维场景】
{scene_desc}

【已确定的 LoadDataSchema（本 Skill 会拉取的数据来源）】
{schema_json}

请编写运维分析 Prompt，要求包含以下结构：
1. 角色设定：描述这是哪类场景的分析专家
2. ## 输入数据（必须保留此行作为占位符，该行后不要加任何内容）
3. ## 分析流程：根据上面的数据源，设计逐步分析步骤（每个数据源对应一个分析步骤）
4. ## 输出要求：规定 LLM 输出 JSON 格式，必须包含 conclusion 字段（值为"需要关注"或"不需要关注"）

直接输出 Prompt 文本（不要加代码块标记）："""


def _validate_stage2(prompt_text: str) -> Tuple[bool, str]:
    """
    Validate Stage2 LLM output.
    Returns (ok, error_reason).
    Checks: non-empty / contains "## 输入数据" / contains "## 输出要求" / brackets balanced
    Output format (alert conclusion / inspection outputs+summary) is determined by LLM per scene, not enforced.
    """
    info_log(f"Stage2 output Prompt raw text: {prompt_text}")
    if not prompt_text or not prompt_text.strip():
        return False, "Prompt text is empty"
    if "## 输入数据" not in prompt_text:
        return False, "Prompt missing '## 输入数据' placeholder, required for data injection during Skill execution"
    if "conclusion" not in prompt_text:
        return False, "Prompt output format missing 'conclusion' field, required for system to parse LLM conclusion"
    if "## 输出要求" not in prompt_text:
        return False, "Prompt missing '## 输出要求' section, required to specify LLM output JSON format"
    # Check bracket balance after ## 输出要求 (catch truncated output)
    output_req_section = prompt_text[prompt_text.index("## 输出要求"):]
    depth_curly = 0
    depth_square = 0
    found_any_bracket = False
    for ch in output_req_section:
        if ch == "{":
            depth_curly += 1
            found_any_bracket = True
        elif ch == "}":
            depth_curly -= 1
        elif ch == "[":
            depth_square += 1
            found_any_bracket = True
        elif ch == "]":
            depth_square -= 1
    if found_any_bracket and (depth_curly != 0 or depth_square != 0):
        return False, (
            f"Prompt '## 输出要求' section has incomplete JSON structure (output may be truncated), "
            f"unclosed brackets: {{={depth_curly}, [={depth_square}"
        )
    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Generic LLM retry wrapper
# ─────────────────────────────────────────────────────────────────────────────

def _llm_with_retry(
    system_prompt: str,
    user_prompt: str,
    validate_fn: Callable[[str], Tuple[bool, str]],
    request_id: str,
    stage_name: str,
) -> str:
    """
    Call LLM; on validation failure, append error to user_prompt and retry.
    Max retries: _MAX_RETRIES (total attempts = _MAX_RETRIES + 1).
    Returns output text on success; raises SkillCreateError if all attempts fail.
    """
    current_prompt = user_prompt
    last_error = ""
    for attempt in range(_MAX_RETRIES + 1):
        info_log(f"skill_create: [{request_id}] {stage_name} attempt {attempt + 1}")
        output: str = llm_call(
            user_prompt=current_prompt,
            system_prompt=system_prompt,
            request_id=f"{request_id}_{stage_name}_attempt{attempt + 1}",
        )
        ok, reason = validate_fn(output)
        if ok:
            info_log(f"skill_create: [{request_id}] {stage_name} attempt {attempt + 1} succeeded")
            return output
        last_error = reason
        info_log(
            f"skill_create: [{request_id}] {stage_name} attempt {attempt + 1} failed: {reason}"
        )
        if attempt < _MAX_RETRIES:
            # Append error info to prompt, guiding LLM to correct
            current_prompt = (
                user_prompt
                + f"\n\n【上次输出有误，请修正后重新输出】\n"
                f"错误原因: {reason}\n"
                f"上次输出（供参考）:\n{output}\n\n"
                f"请根据错误原因修正后重新输出："
            )

    raise SkillCreateError(
        f"skill_create [{request_id}]: {stage_name} failed after {_MAX_RETRIES + 1} attempts, "
        f"last error: {last_error}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reference Skill generation: summary extraction + reference info block construction
# ─────────────────────────────────────────────────────────────────────────────

_SUMMARIZE_SYSTEM_PROMPT = """\
你是一名运维 Skill 分析专家。
你的任务是：阅读下面的运维分析 Prompt，提炼出其核心决策逻辑，输出 2-6 句话的摘要。

【要求】
- 重点提炼"在什么条件下得出什么结论"的判断规则，而非步骤顺序
- 说明核心指标/事件及其判断阈值或关联条件
- 说明知识库命中后的短路规则（如果有）
- 直接输出摘要文本，不要加任何前缀或格式标记
"""


def _summarize_skill_prompt(prompt_text: str, request_id: str) -> str:
    """
    Call LLM to summarize a single Skill's prompt into a core decision logic summary (2-4 sentences).
    On failure, returns empty string and logs the error; does not block main flow.
    """
    if not prompt_text or not prompt_text.strip():
        return ""
    try:
        summary = llm_call(
            user_prompt=prompt_text,
            system_prompt=_SUMMARIZE_SYSTEM_PROMPT,
            request_id=f"{request_id}_summarize",
        )
        info_log(f"skill_create: [{request_id}] summary generated: {summary}...")
        return summary.strip()
    except Exception as e:
        info_log(f"skill_create: [{request_id}] summary generation failed (degraded to empty): {e}")
        return ""


def _build_ref_schema_block(ref_skill_docs) -> str:
    """
    Build Stage1 reference info block: show data source type list for each reference Skill.
    ref_skill_docs: List[SkillDoc], loaded reference Skill objects.
    Returns empty string if empty.
    """
    if not ref_skill_docs:
        return ""
    lines = ["【同类场景可参考的数据源选择，**注意不能直接复用!！！**】"]
    for skill in ref_skill_docs:
        type_list = [entry.get("type", "") for entry in (skill.load_data_schema or []) if entry.get("type")]
        tags_str = ", ".join(skill.tags) if skill.tags else "no tags"
        types_str = ", ".join(type_list) if type_list else "no data sources"
        lines.append(f"- {skill.name}（tags: {tags_str}）：{types_str}")
    return "\n".join(lines)


def _build_ref_prompt_block(ref_skill_docs, summaries: List[str]) -> str:
    """
    Build Stage2 reference info block: show each reference Skill's prompt + decision logic summary.
    ref_skill_docs: List[SkillDoc], summaries: List[str] (paired with ref_skill_docs).
    Returns empty string if empty.
    """
    if not ref_skill_docs:
        return ""
    parts = ["【参考 Skill 分析逻辑（供参考，请根据当前场景适当调整）】"]
    for i, skill in enumerate(ref_skill_docs):
        summary = summaries[i] if i < len(summaries) else ""
        tags_str = ", ".join(skill.tags) if skill.tags else "no tags"
        header = f"--- {skill.name}（tags: {tags_str}）---"
        parts.append(header)
        if summary:
            parts.append("[决策逻辑摘要]")
            parts.append(summary)
        parts.append("[完整 Prompt]")
        parts.append(skill.prompt or "（无 Prompt 内容）")
    return "\n".join(parts)


def create_skill_with_reference(parsed_input: ParsedInput, related_skills: List[str]) -> str:
    """Create new Skill with reference to existing Skills."""
    request_id = parsed_input.request_id

    # ── Step 1: Load reference Skill objects ────────────────────────────────────
    ref_skill_docs = []
    for skill_name in related_skills:
        doc = skill_md_manager.get(skill_name)
        if doc is None:
            info_log(f"skill_create: [{request_id}] reference Skill [{skill_name}] not found, skip")
        else:
            ref_skill_docs.append(doc)
            info_log(f"skill_create: [{request_id}] loaded reference Skill [{skill_name}]")

    # ── Step 2: Fallback ──────────────────────────────────────────────────────
    if not ref_skill_docs:
        info_log(
            f"skill_create: [{request_id}] all reference Skills invalid, falling back to standard skill_create flow"
        )
        # Reuse skill_create main logic
        return skill_create(parsed_input, related_skills=[])

    # ── Step 3: Summary preprocessing ────────────
    ref_summaries: List[str] = []
    for i, doc in enumerate(ref_skill_docs):
        summary = _summarize_skill_prompt(
            prompt_text=doc.prompt,
            request_id=f"{request_id}_ref{i}_{doc.name}",
        )
        ref_summaries.append(summary)

    # ── Step 4: Generate name / tags / scene_desc ───────────────────────────────
    name = f"{parsed_input.business_id}-{parsed_input.scene_id}-skill"
    tags = [parsed_input.scene_id]
    scene_desc = _build_scene_desc(parsed_input)
    info_log(f"skill_create(ref): [{request_id}] name={name}, scene_desc=\n{scene_desc}")

    # ── Step 5: Load data source info ───────────────────────────────────────────
    summary_table = _load_summary_table()
    valid_types = _load_valid_types()

    # ── Step 6: Stage1 LLM → generate LoadDataSchema ──────────────────────────
    ref_schema_block = _build_ref_schema_block(ref_skill_docs)
    stage1_base = _build_stage1_user_prompt(scene_desc, summary_table)
    # Append reference info block to original prompt
    if ref_schema_block:
        stage1_user = stage1_base.rstrip() + f"\n\n{ref_schema_block}\n\n请根据上面的场景和参考信息，输出 LoadDataSchema JSON（只输出 JSON，不带任何额外文字）："
    else:
        stage1_user = stage1_base

    info_log(f"skill_create(ref): [{request_id}] stage1_user_prompt:\n{stage1_user}")
    schema_raw = _llm_with_retry(
        system_prompt=_STAGE1_SYSTEM_PROMPT,
        user_prompt=stage1_user,
        validate_fn=lambda out: _validate_stage1(out, valid_types),
        request_id=request_id,
        stage_name="Stage1(ref-LoadDataSchema)",
    )
    stage1_reasoning, schema_text = _extract_stage1_parts(schema_raw)
    info_log(f"skill_create(ref): [{request_id}] stage1 - data source selection rationale:\n{stage1_reasoning}")
    load_data_schema = json.loads(schema_text)
    info_log(
        f"skill_create(ref): [{request_id}] Stage1 done, "
        f"schema entries={len(load_data_schema)}, "
        f"types={[e.get('type') for e in load_data_schema]}"
    )

    # ── Step 7: Stage2 LLM → generate Prompt text ────────────────────────────
    schema_json_str = json.dumps(load_data_schema, indent=2, ensure_ascii=False)
    ref_prompt_block = _build_ref_prompt_block(ref_skill_docs, ref_summaries)
    stage2_base = _build_stage2_user_prompt(scene_desc, schema_json_str)
    # Append reference info block to original prompt
    if ref_prompt_block:
        stage2_user = stage2_base.rstrip() + f"\n\n{ref_prompt_block}\n\n请参考以上 Skill 的分析逻辑，结合当前场景直接输出 Prompt 文本（不要加代码块标记）："
    else:
        stage2_user = stage2_base

    info_log(f"skill_create(ref): [{request_id}] stage2_user_prompt:\n{stage2_user}")
    prompt_text = _llm_with_retry(
        system_prompt=_load_stage2_system_prompt(parsed_input.scene_id),
        user_prompt=stage2_user,
        validate_fn=_validate_stage2,
        request_id=request_id,
        stage_name="Stage2(ref-Prompt)",
    )
    info_log(f"skill_create(ref): [{request_id}] final prompt:\n{prompt_text}")

    # ── Step 8: Write Skill file ──────────────────────────────────────────────
    final_name = name
    counter = 2
    while skill_md_manager.get(final_name) is not None:
        final_name = f"{name}_{counter}"
        counter += 1
    if final_name != name:
        info_log(
            f"skill_create(ref): [{request_id}] Skill [{name}] already exists, "
            f"using new name [{final_name}]"
        )

    biz_list = parsed_input.biz_list
    if not biz_list or len(biz_list) == 0:
        biz_list = [_DEFAULT_BUSINESS_ALIAS]
    description = f"Auto-generated (ref Skill): {parsed_input.scene_id} scenario {biz_list} business Skill"
    overview = f"Auto-generated by create_skill_with_reference (request_id={request_id}), ref Skills: {[d.name for d in ref_skill_docs]}"
    try:
        skill_path = skill_md_manager.add(
            name=final_name,
            description=description,
            load_data_schema=load_data_schema,
            prompt=prompt_text,
            tags=tags,
            overview=overview,
            business=biz_list,
        )
    except Exception as e:
        raise SkillCreateError(
            f"create_skill_with_reference [{request_id}]: failed to write Skill file: {e}"
        ) from e

    info_log(
        f"skill_create(ref): [{request_id}] Skill write complete "
        f"name={final_name}, path={skill_path}"
    )
    return final_name

# ─────────────────────────────────────────────────────────────────────────────
# Main function
# ─────────────────────────────────────────────────────────────────────────────

def skill_create(parsed_input: ParsedInput, related_skills : List[str]) -> str:
    """
    Two-stage Skill file generation.

    Stage1: scene description + data source capability list -> LLM -> LoadDataSchema (JSON)
    Stage2: scene description + LoadDataSchema + reference Skill content -> LLM -> Prompt text
    Final: call SkillManager.add to write Skill file, return skill name.

    Args:
        parsed_input: parsed unified input structure

    Returns:
        generated Skill name (written as the name field in the file)

    Raises:
        SkillCreateError: any stage failure (including retry exhaustion, file write failure)
    """
    request_id = parsed_input.request_id
    
    if len(related_skills) > 0:
        info_log(f"skill_create: [{request_id}] generating skill from related_skills")
        return create_skill_with_reference(parsed_input, related_skills)

    # ── Step 1: Generate name / business / tags ───────────────────────────────
    name = f"{parsed_input.business_id}-{parsed_input.scene_id}-skill"
    tags = [parsed_input.scene_id]
    scene_desc = _build_scene_desc(parsed_input)
    info_log(f"[{request_id}] name={name}, scene_desc={scene_desc}, tags={tags}")

    # ── Step 2: Load data source info ───────────────────────────────────────────
    # summary table for LLM to decide which data sources to select
    summary_table = _load_summary_table()
    # info_log(f"[{request_id}] summary_table:\n{summary_table}")
    # valid_types extracted from data_lake.yaml capabilities, used for validating LLM output type legality
    valid_types = _load_valid_types()
    # info_log(f"[{request_id}] valid_types:\n{valid_types}")

    # ── Step 3: Stage1 LLM → generate LoadDataSchema ──────────────────────────
    stage1_user = _build_stage1_user_prompt(scene_desc, summary_table)

    schema_raw = _llm_with_retry(
        system_prompt=_STAGE1_SYSTEM_PROMPT,
        user_prompt=stage1_user,
        validate_fn=lambda out: _validate_stage1(out, valid_types),
        request_id=request_id,
        stage_name="Stage1(LoadDataSchema)",
    )
    # Split reasoning (selection rationale) and JSON, log separately
    stage1_reasoning, schema_text = _extract_stage1_parts(schema_raw)
    info_log(
        f"skill_create: [{request_id}] stage1 - data source selection rationale:\n{stage1_reasoning}"
    )
    load_data_schema = json.loads(schema_text)
    info_log(
        f"skill_create: [{request_id}] Stage1 done, "
        f"schema entries={len(load_data_schema)}, "
        f"types={[e.get('type') for e in load_data_schema]}"
    )

    # ── Step 4: Stage2 LLM → generate Prompt text ────────────────────────────
    schema_json_str = json.dumps(load_data_schema, indent=2, ensure_ascii=False)
    stage2_user = _build_stage2_user_prompt(scene_desc, schema_json_str)
    prompt_text = _llm_with_retry(
        system_prompt=_load_stage2_system_prompt(parsed_input.scene_id),
        user_prompt=stage2_user,
        validate_fn=_validate_stage2,
        request_id=request_id,
        stage_name="Stage2(Prompt)",
    )

    # ── Step 5: Write Skill file ──────────────────────────────────────────────
    # If same-name file exists, append sequence suffix until unique (name_2, name_3, ...)
    final_name = name
    counter = 2
    while skill_md_manager.get(final_name) is not None:
        final_name = f"{name}_{counter}"
        counter += 1
    if final_name != name:
        info_log(
            f"skill_create: [{request_id}] Skill [{name}] already exists, "
            f"using new name [{final_name}]"
        )

    biz_list = parsed_input.biz_list
    if not biz_list or len(biz_list) == 0:
        biz_list = [_DEFAULT_BUSINESS_ALIAS]
    description = f"Auto-generated: {parsed_input.scene_id} scenario {biz_list} business Skill"
    overview = f"Auto-generated by skill_create (request_id={request_id})"
    try:
        skill_path = skill_md_manager.add(
            name=final_name,
            description=description,
            load_data_schema=load_data_schema,
            prompt=prompt_text,
            tags=tags,
            overview=overview,
            business=biz_list,
        )
    except Exception as e:
        raise SkillCreateError(f"skill_create [{request_id}]: failed to write Skill file: {e}") from e

    info_log(
        f"skill_create: [{request_id}] Skill write complete "
        f"name={final_name}, path={skill_path}"
    )
    return final_name

# ─────────────────────────────────────────────────────────────────────────────
# Feedback update main function
# ─────────────────────────────────────────────────────────────────────────────
def feedback_skill_data_prompt_update(
      skill_doc: SkillDoc,  # Exactly matched Skill (will be used as template for update)
      data_changes: Optional[str],
      prompt: Optional[str],
    ) -> str:
    """
    Based on exactly matched Skill as template, update Skill file content with user feedback (in-place overwrite).
    Uses SkillManager.update to write back; no new file is created.
    Returns skill name.
    """
    manager = SkillManager.instance()
    skill_name = skill_doc.name

    # If data_changes is non-empty, use LLM to update load_data_schema; otherwise keep original Skill's schema
    if data_changes and data_changes.strip():
        # Load data capability table (same as feedback_skill_create / stage1, for LLM to select correct type)
        summary_table = _load_summary_table()

        # Parse data name -> metric_name mapping from summary table, for LLM to fill metric_name accurately
        metric_name_map = _parse_metric_name_map()
        metric_name_map_text = "".join(
            f"  {name}: {metric}\n" for name, metric in metric_name_map.items()
        )

        # Use LLM based on matched Skill's schema + data_changes to generate new load_data_schema
        _FEEDBACK_SCHEMA_SYSTEM_PROMPT = """\
你是一名运维 Skill 数据配置专家。
你的任务是：根据用户反馈的变更说明，对已有的 LoadDataSchema JSON 进行增删修改，输出修改后的完整 LoadDataSchema JSON。

【规则】
- 只输出修改后的 JSON 数组，不要任何额外说明或代码块标记（```）
- 严格按照用户描述进行增删，未提及的条目保持不变
- 每个 type 必须严格与【可用数据能力表】中的 type 字段完全一致，禁止自造 type
- 对于服务对QPS、CPU、内存、耗时等，必须使用【可用数据能力表】中对应的独立 type（如 qps_info、cpu_info、mem_info、latency_info），不要用 tianwen_metric 代替
- tianwen_metric 仅用于【可用数据能力表】中明确标注 type=tianwen_metric 的数据（如服务可用性等），且必须包含 metric_name 字段
- metric_name 必须从下方「指标名称映射表」中查找对应值，不得自行猜测
- 若某条 tianwen_metric params_list 中的某项被删除后 params_list 为空，则删除整条 entry"""

        feedback_schema_user_prompt = f"""【可用数据能力表（表格列: 数据名称 | type | 说明 | metric_name | 限制）】
{summary_table}

【指标名称映射表（tianwen_metric 专用，数据名称 -> metric_name）】
{metric_name_map_text}
【当前 LoadDataSchema】
{json.dumps(skill_doc.load_data_schema, indent=2, ensure_ascii=False)}

【用户反馈的变更说明】
{data_changes}

请根据变更说明和可用数据能力表，输出修改后的完整 LoadDataSchema JSON："""

        valid_types = _load_valid_types()
        schema_raw = _llm_with_retry(
            system_prompt=_FEEDBACK_SCHEMA_SYSTEM_PROMPT,
            user_prompt=feedback_schema_user_prompt,
            validate_fn=lambda out: _validate_stage1(out, valid_types),
            request_id=f"feedback-update-{skill_name}",
            stage_name="feedback_schema",
        )
        _, schema_text = _extract_stage1_parts(schema_raw)
        new_load_data_schema: List[Dict[str, Any]] = json.loads(schema_text)
        info_log(
            f"feedback_skill_data_prompt_update: [{skill_name}] new schema generated, "
            f"types={[e.get('type') for e in new_load_data_schema]}"
        )
    else:
        new_load_data_schema = skill_doc.load_data_schema
        info_log(
            f"feedback_skill_data_prompt_update: [{skill_name}] no data_changes, keeping original schema, "
            f"types={[e.get('type') for e in new_load_data_schema]}"
        )

    _FEEDBACK_PROMPT_UPDATE_SYSTEM_PROMPT = """\
你是一名运维 Skill prompt 编辑专家，负责对已有的运维分析 prompt 进行精准的局部修改。

【核心原则】
你的工作是"外科手术式"修改：仅改动用户明确指出的部分，其余所有内容（结构、措辞、格式、步骤编号、字段名称）原封不动保留。

【输出格式】
- 只输出修改后的完整 prompt 文本，不附加任何解释、前缀、后缀或代码块标记（```）
- 严格保持原文的 Markdown 格式（标题层级、加粗、列表缩进、换行）
- 不得改变未涉及章节的任何措辞，包括标点和空格

【修改操作语义】
以下为用户说明中常见表达的对应操作，请严格执行：
- "不需要 / 去掉 / 删除 X"：删除 prompt 中所有涉及 X 的分析步骤、字段引用和关联逻辑，若某步骤因此变为空步骤则同时删除该步骤标题
- "需要 / 增加 / 补充 X"：在语义最合适的位置插入 X 相关的分析说明，不新增冗余步骤
- "X 应该 / 需要根据 Y 进行关联"：找到 prompt 中描述 X 的关联逻辑处，将其替换或补充为"必须结合 Y 进行关联验证"的表述
- "X 改为 Y"：精确替换对应措辞，不影响上下文

【禁止行为】
- 禁止合并、拆分、重排现有步骤
- 禁止对未提及的字段、指标、逻辑做任何改动
- 禁止添加用户未要求的新分析逻辑或结论规则
- 禁止改变输出格式要求（如 JSON 格式要求须原样保留）"""

    # If caller provided prompt modification instructions, use LLM to revise original prompt; otherwise keep original Skill's prompt
    if prompt:
        feedback_prompt_update_user_prompt = f"""【当前 prompt】
{skill_doc.prompt}

【用户反馈的修改说明】
{prompt}

请根据修改说明，输出修改后的完整 prompt："""

        final_prompt = _llm_with_retry(
            system_prompt=_FEEDBACK_PROMPT_UPDATE_SYSTEM_PROMPT,
            user_prompt=feedback_prompt_update_user_prompt,
            validate_fn=lambda out: (bool(out and out.strip()), "Output is empty"),
            request_id=f"feedback-update-{skill_name}",
            stage_name="feedback_prompt",
        )
        info_log(
            f"feedback_skill_data_prompt_update: [{skill_name}] new prompt generated"
        )
    else:
        final_prompt = skill_doc.prompt
        info_log(
            f"feedback_skill_data_prompt_update: [{skill_name}] no prompt modification, keeping original prompt"
        )
    info_log(f"feedback_skill_data_prompt_update: [{skill_name}] final prompt:\n{final_prompt}")

    # One-shot full replacement of load_data_schema + prompt, avoiding multiple writes per entry
    # Take current in-memory cached SkillDoc and replace schema + prompt on top of it
    cached_doc = manager.get(skill_name)
    if cached_doc is None:
        raise RuntimeError(f"feedback_skill_update: Skill [{skill_name}] not found in SkillManager cache")

    import copy
    updated_doc = copy.deepcopy(cached_doc)
    updated_doc.load_data_schema = new_load_data_schema
    if final_prompt != cached_doc.prompt:
        updated_doc.prompt = final_prompt

    # Write the modified SkillDoc directly back to conf, one call to complete
    from app.skill_explore.skill_md_manager import _render_skill_md, _bump_version
    updated_doc.version = _bump_version(updated_doc.version)
    md_text = _render_skill_md(updated_doc)
    from app.framework.conf.conf_manager import get_conf_manager
    ok = get_conf_manager().set_skill_content(skill_name, md_text)
    if not ok:
        raise OSError(f"feedback_skill_update: conf write-back skill [{skill_name}] failed")

    # Sync in-memory cache
    manager._cache[updated_doc.name] = updated_doc
    info_log(
        f"feedback_skill_update: [{skill_name}] schema full replacement done, "
        f"types={[e.get('type') for e in new_load_data_schema]}"
    )

    info_log(f"feedback_skill_update: [{skill_name}] Skill update complete")
    return skill_name

