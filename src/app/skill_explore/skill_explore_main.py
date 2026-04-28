'''
Skill creation & execution analysis entry file
'''
from typing import Any, Dict, List, Optional

from app.util.logger import error_log, info_log
from app.skill_explore.skill_create import skill_create
from app.skill_explore.input_parser import ParsedInput, get_parser
from app.skill_explore.skill_md_manager import SkillDoc, SkillManager
from app.skill_explore.skill_search import search_skill
from app.skill_explore.skill_executor import execute_skill

# ─────────────────────────────────────────────────────────────────────────────
# [Skill not found] LLM generates new Skill
# ────────────────────────────────────────────────────────────────────────────
def _create_skill_placeholder(parsed: ParsedInput, related_skills : List[str]) -> Optional[SkillDoc]:
    info_log(f"[skill_explore] [create_skill] Generating Skill — business_id=[{parsed.business_id}] scene_id=[{parsed.scene_id}]")
    skill_name = skill_create(parsed_input=parsed, related_skills=related_skills)
    if skill_name:
        skill_doc = SkillManager.instance().get(skill_name)
        return skill_doc
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point (alert scenario)
# ─────────────────────────────────────────────────────────────────────────────

def run_warning(
    data,
    request_id: str = ""
) -> Dict[str, Any]:
    """
    Alert scenario main entry point
    """
    _SEP = "-" * 50
    info_log(f"\n{_SEP}\n Request received\n Pipeline: 1.Parse → 2.Skill Search [or Skill Create] → 3.Execute\n{_SEP}")
    info_log(f"\n{_SEP}\n [Step 1] Parse Request\n{_SEP}")

    parser = get_parser()
    parsed = parser.parse_warning(data, request_id=request_id)
    
    if parsed is None:
        error_log("skill_explore_main: [warning] parse_warning returned None, cannot process this request")
        return {"payload": {}, "conclusion": "", "raw_output": "", "success": False}

    info_log(f"[Step 1] Parsed — request_id=[{parsed.request_id}] business_id=[{parsed.business_id}] scene_id=[{parsed.scene_id}]")
    
    return _run_skill_flow(parsed)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point (inspection scenario)
# ─────────────────────────────────────────────────────────────────────────────

def run_inspect(
    biz: str = "",
    rule_id: str = "",
    request_id: str = "",
    timestamp: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Inspection scenario main entry point
    """
    # ── Parse input ──────────────────────────────────────────────────────────────
    # Call input_parser adapter to convert biz + rule_id query params into unified ParsedInput structure
    parser = get_parser()
    parsed = parser.parse_inspect(biz=biz, rule_id=rule_id, request_id=request_id, timestamp=timestamp)
    
    if parsed is None:
        error_log(f"skill_explore_main: [inspection] parse failed")
        raise ValueError("parse inspection data failed")

    info_log(
        f"skill_explore_main: [inspect] parsed —"
        f" request_id=[{parsed.request_id}]"
        f" business_id=[{parsed.business_id}]"
        f" scene_id=[{parsed.scene_id}]"
        f" timestamp=[{parsed.timestamp}]"
    )

    return _run_skill_flow(parsed)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point (blocking scenario)
# ─────────────────────────────────────────────────────────────────────────────

def run_release(
    data,
    request_id: str = ""
) -> Dict[str, Any]:
    """
    Blocking scenario main entry point
    """
    # ── Parse input ──────────────────────────────────────────────────────────────
    # Call input_parser adapter to convert biz + rule_id query params into unified ParsedInput structure
    parser = get_parser()
    parsed = parser.parse_release(data, request_id=request_id)

    if parsed is None:
        error_log(f"skill_explore_main: [release] parse failed")
        raise ValueError("parse release data failed")

    info_log(
        f"skill_explore_main: [inspect] parsed —"
        f" request_id=[{parsed.request_id}]"
        f" business_id=[{parsed.business_id}]"
        f" scene_id=[{parsed.scene_id}]"
        f" timestamp=[{parsed.timestamp}]"
    )

    return _run_skill_flow(parsed)

# ─────────────────────────────────────────────────────────────────────────────
# Core execution flow: Skill search/create -> load -> workflow execution
# ─────────────────────────────────────────────────────────────────────────────

def _run_skill_flow(
    parsed: ParsedInput
) -> Dict[str, Any]:
    """
    execution flow
    """
    request_id = parsed.request_id
    _SEP = "-" * 50

    info_log(f"\n{_SEP}\n [Step 2] Skill Search\n{_SEP}")
    skill_name, related_skills = search_skill(parsed)
    info_log(f"[Step 2] Search result — skill=[{skill_name!r}]")

    skill: Optional[SkillDoc] = None

    if skill_name != "":
        skill = SkillManager.instance().get(skill_name)
        if skill is None:
            error_log(f"skill_explore_main: [{request_id}] skill_search matched [{skill_name}] but not found in cache, falling back to create_skill")

    if skill is None:
        info_log(f"\n{_SEP}\n [Step 2] No skill matched, creating new Skill\n{_SEP}")
        info_log(f"[Step 2] create_skill — business_id=[{parsed.business_id}] scene_id=[{parsed.scene_id}]")
        skill = _create_skill_placeholder(parsed, related_skills)

    if skill is None:
        error_log(
            f"skill_explore_main: [{request_id}]"
            f" create_skill failed, no Skill available, returning empty result"
        )
        return {"payload": {}, "conclusion": "", "raw_output": "", "success": False}

    result = execute_skill(
        skill=skill,
        parsed_input=parsed
    )

    return result
