"""
Data Provider Registry — Data capability registration center

Responsibility: map the type string in Skill MD LoadDataSchema to the actual data fetch function.
"""

import os
import traceback
from typing import Any, Callable, Dict, List, Optional

import yaml

from app.util.logger import error_log, info_log

# Import all provider functions from data implementation layer
from app.framework.data.providers import (
    _fetch_data_demo
)

# ─────────────────────────────────────────────────────────────────────────────
# Registry core structure
# ─────────────────────────────────────────────────────────────────────────────

_REGISTRY: Dict[str, Callable[[dict, dict], Any]] = {}


def register(type_key: str, fn: Callable[[dict, dict], Any]) -> None:
    """Register a data provider function. Overwrites previous registration for same type_key and logs."""
    if type_key in _REGISTRY:
        info_log(f"data_provider_registry: type [{type_key}] already exists, overwriting previous registration")
    _REGISTRY[type_key] = fn
    info_log(f"data_provider_registry: registered type=[{type_key}] fn={fn.__name__}")


def get_provider(type_key: str) -> Optional[Callable[[dict, dict], Any]]:
    """Get data provider function by type_key. Returns None if not found."""
    return _REGISTRY.get(type_key)


def list_providers() -> List[str]:
    """Return all registered type_key list, for LLM reference when generating Skills."""
    return list(_REGISTRY.keys())


# ─────────────────────────────────────────────────────────────────────────────
# YAML-driven auto-registration
# ─────────────────────────────────────────────────────────────────────────────

_DATA_LAKE_YAML_PATH = os.path.join(os.path.dirname(__file__), "data_lake.yaml")

# Parsed YAML config cache (for LLM consumption interface)
_DATA_LAKE_CONFIG: Optional[Dict[str, Any]] = None


def _load_and_register_from_yaml() -> None:
    """
    Read data capability config from data_lake.yaml, auto-register register(type, handler).

    Load flow:
        1. Read and parse data_lake.yaml
        2. Iterate capabilities list
        3. Find callable handler function by name via globals() (from providers module import)
        4. Call register(type_key, fn) to complete registration
        5. On handler lookup failure, log error and skip that entry; do not block startup
    """
    global _DATA_LAKE_CONFIG

    if not os.path.exists(_DATA_LAKE_YAML_PATH):
        error_log(
            f"data_provider_registry: data_lake.yaml not found: {_DATA_LAKE_YAML_PATH}, "
            "skipping auto-registration"
        )
        return

    try:
        with open(_DATA_LAKE_YAML_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception:
        error_log(
            "data_provider_registry: data_lake.yaml parse failed\n"
            + traceback.format_exc()
        )
        return

    if not config or not isinstance(config.get("capabilities"), list):
        error_log("data_provider_registry: data_lake.yaml format error, missing capabilities list")
        return

    _DATA_LAKE_CONFIG = config
    _this_module = globals()
    registered_count = 0

    for cap in config["capabilities"]:
        type_key = cap.get("type", "")
        handler_name = cap.get("handler", "")

        if not type_key or not handler_name:
            error_log(
                f"data_provider_registry: data_lake.yaml entry missing type or handler, skip: {cap}"
            )
            continue

        fn = _this_module.get(handler_name)
        if fn is None or not callable(fn):
            error_log(
                f"data_provider_registry: handler [{handler_name}] not found or not callable, "
                f"type=[{type_key}] registration skipped"
            )
            continue

        register(type_key, fn)
        registered_count += 1

    info_log(
        f"data_provider_registry: data_lake.yaml loaded, "
        f"registered {registered_count}/{len(config['capabilities'])} data capabilities"
    )


# Auto-execute on module load
_load_and_register_from_yaml()


# ─────────────────────────────────────────────────────────────────────────────
# LLM consumption interface — provides data capability catalog for Skill generation
# ─────────────────────────────────────────────────────────────────────────────

def get_data_lake_catalog() -> Dict[str, Any]:
    """
    Return the full parsed config dict from data_lake.yaml.
    If YAML was not loaded successfully, returns empty dict {}.
    """
    return _DATA_LAKE_CONFIG if _DATA_LAKE_CONFIG else {}


def get_data_lake_summary() -> str:
    """
    Return formatted data capability catalog text, directly injectable into LLM prompt.

    Output format example:
        ## Available Data Capability List

        ### 1. demo
        - Description: Demo provider for end-to-end testing
        - Params: ...
        - depends on context: service_name, timestamp, request_id
        - Return type: dict
        ...
    """
    if not _DATA_LAKE_CONFIG or not _DATA_LAKE_CONFIG.get("capabilities"):
        return "## Available Data Capability List\n\n(No registered data capabilities yet)"

    lines: List[str] = ["## Available Data Capability List", ""]

    for idx, cap in enumerate(_DATA_LAKE_CONFIG["capabilities"], 1):
        type_key = cap.get("type", "unknown")
        desc = cap.get("description", "")
        params = cap.get("params", {})
        context_keys = cap.get("context_keys", [])
        return_type = cap.get("return_type", "Any")
        return_default = cap.get("return_default", "None")

        lines.append(f"### {idx}. {type_key}")
        lines.append(f"- Description: {desc}")

        if params:
            lines.append("- Params:")
            for p_name, p_info in params.items():
                p_type = p_info.get("type", "Any") if isinstance(p_info, dict) else "Any"
                p_default = p_info.get("default", "") if isinstance(p_info, dict) else ""
                p_desc = p_info.get("description", "") if isinstance(p_info, dict) else ""
                p_required = p_info.get("required", False) if isinstance(p_info, dict) else False
                if p_required:
                    lines.append(f"  - {p_name} ({p_type}, **required**): {p_desc}")
                elif p_default:
                    lines.append(f"  - {p_name} ({p_type}, default={p_default}): {p_desc}")
                else:
                    lines.append(f"  - {p_name} ({p_type}): {p_desc}")
        else:
            lines.append("- Params: None")

        if context_keys:
            lines.append(f"- depends on context: {', '.join(context_keys)}")

        lines.append(f"- Return type: {return_type}")
        lines.append(f"- Failure default: {return_default}")
        lines.append("")

    return "\n".join(lines)