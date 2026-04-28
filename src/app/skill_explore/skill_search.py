from typing import List, Tuple

from app.util.logger import info_log
from app.skill_explore.input_parser import ParsedInput
from app.skill_explore.skill_md_manager import SkillDoc, SkillManager

_BUSINESS_NORMAL = "normal"


def search_skill(parsed: ParsedInput) -> Tuple[str, List[str]]:
    """
    Search for the best-matching Skill based on biz_list * scene_id.

    Matching strategy:
      1. Exact match: scene_id in doc.tags AND biz_list equals doc.business -> return first
      2. No exact match: rank by relevance score (scene match weight > business intersection count), take Top 3 as reference

    Relevance score: scene match +10, each business intersection +1
    """
    biz_list = parsed.biz_list
    scene_id = parsed.scene_id

    info_log(f"[skill_search] Search — biz_list={biz_list} scene_id=[{scene_id}]")

    manager = SkillManager.instance()
    all_skills = manager.all()

    if not all_skills:
        info_log(f"[skill_search] No skills loaded")
        return "", []

    biz_set = set(biz_list)

    for doc in all_skills.values():
        scene_hit = scene_id in doc.tags
        biz_hit = biz_set == set(doc.business)
        if scene_hit and biz_hit:
            info_log(f"[skill_search] Matched [{doc.name}]")
            return doc.name, []

    scored: List[Tuple[int, str]] = []
    for doc in all_skills.values():
        score = 0
        if scene_id in doc.tags:
            score += 10
        score += len(biz_set & set(doc.business))
        if score > 0:
            scored.append((score, doc.name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    related_skills = [name for _, name in scored[:3]]

    info_log(f"[skill_search] No exact match, related Top3={related_skills}")
    return "", related_skills
