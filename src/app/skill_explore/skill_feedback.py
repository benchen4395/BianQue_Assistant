"""
Skill Explore feedback processing module
"""

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.util.logger import error_log, info_log
from app.skill_explore.skill_md_manager import SkillDoc, SkillManager
from app.skill_explore.skill_search import search_skill
from app.skill_explore.input_parser import ParsedInput
from app.skill_explore.skill_create import feedback_skill_data_prompt_update


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────

def _skill_to_dict(doc: SkillDoc) -> Dict[str, Any]:
    return {
        "name": doc.name,
        "description": doc.description,
        "version": doc.version,
        "business": doc.business,
        "tags": doc.tags,
        "overview": doc.overview,
        "load_data_schema": doc.load_data_schema,
        "prompt": doc.prompt,
        "source_path": doc.source_path,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Feedback result data structure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SkillFeedbackResult:
    success: bool
    message: str = ""
    skill_name: str = ""
    action: str = ""
    skill_content: Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_skill_feedback_new(
    scene_id: str,
    biz_list: Optional[List[str]] = None,
    data_changes: Optional[str] = None,
    prompt: Optional[str] = None,
    request_id: str = ""
) :
    """
    Skill content feedback unified entry point.
    """
    info_log(
        f"skill_feedback: [{request_id}] feedback received"
        f" biz_list=[{biz_list}] scene_id=[{scene_id}]"
        f" data_changes={data_changes} prompt_len={len(prompt or '')}"
    )

    if scene_id == "":
        error_log(f"skill_feedback: [{request_id}] scene_id is empty")
        return None

    if not data_changes and not prompt:
        error_log(f"skill_feedback: [{request_id}] both data_changes and prompt are empty")
        return None

    if not biz_list:
        error_log(f"skill_feedback: [{request_id}] biz_list is empty")
        return None

    # Construct ParsedInput to reuse search_skill matching logic
    parsed = ParsedInput(
        request_id=request_id,
        business_id="",
        biz_list=biz_list,
        scene_id=scene_id,
        context={},
        source="feedback",
        timestamp=0
    )

    skill_name, _ = search_skill(parsed)
    info_log(f"skill_feedback: [{request_id}] skill_search result=[{skill_name}]")

    # ── Dispatch based on whether Skill exists / exactly matched ────────────────
    if skill_name:
        skill_doc = SkillManager.instance().get(skill_name)
        if skill_doc is None:
            # Rare case: search matched but cache lost
            error_log(f"skill_feedback: [{request_id}] search matched [{skill_name}] but not found in cache")
            return SkillFeedbackResult(
                success=False,
                message=f"Skill [{skill_name}] cache lost, please restart service and retry",
                skill_name=skill_name,
            )

        return _update_skill(skill_doc, data_changes, prompt, request_id)
    else:
        error_log(f"skill_feedback: [{request_id}] skill_search no match")
        return None

def _update_skill(
    skill_doc: SkillDoc,
    data_changes: Optional[str],
    prompt: Optional[str],
    request_id: str):
    """
    Update existing Skill file based on feedback content.
    """
    skill_name = skill_doc.name
    manager = SkillManager.instance()
    
    try:
        new_skill_name = feedback_skill_data_prompt_update(
            skill_doc=skill_doc,
            data_changes=data_changes,
            prompt=prompt,
        )
        if new_skill_name:
            updated_doc = manager.get(new_skill_name)
            return SkillFeedbackResult(
                success=True,
                message=f"Skill [{skill_name}] updated successfully",
                skill_name=new_skill_name,
                action="update",
                skill_content=_skill_to_dict(updated_doc) if updated_doc else None,
            )

        return SkillFeedbackResult(
            success=False,
            message=f"Prompt update failed",
            skill_name=skill_name,
            action="update"
        )
    except Exception as e:
        error_log(f"skill_feedback: [{request_id}] data source update failed: {traceback.format_exc()}")
        return SkillFeedbackResult(
            success=False,
            message=f"Data source update failed: {e}",
            skill_name=skill_name,
            action="update",
        )