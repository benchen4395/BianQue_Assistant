import json
import os
from typing import List

# TODO: Replace this mock implementation with your actual knowledge base integration.
# Current implementation reads from a local JSON file for demo purposes.
# In production, query a vector database, search engine, or internal knowledge API.
# Keep the function signature unchanged: (service_name, topk) -> str
_KNOWLEDGE_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "demo_data", "knowledge.json")
)


def get_knowledge(service_name: str = "", topk: int = 3) -> str:
    """Search knowledge.json by service_name and return matched customized_feedback as text."""
    try:
        with open(_KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            all_items: List[dict] = json.load(f)
    except Exception:
        return ""

    results = []
    for item in all_items:
        item_service_name = item.get("service_name", "")
        if service_name and service_name not in item_service_name and item_service_name not in service_name:
            continue
        feedback = item.get("customized_feedback", "")
        if feedback:
            results.append(feedback)
        if len(results) >= topk:
            break

    return "\n".join(results)
