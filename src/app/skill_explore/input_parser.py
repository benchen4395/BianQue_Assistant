"""
Input parsing module — converts alert/inspection requests into a unified ParsedInput structure.
"""

import json
import os
import re
import time
import uuid as uuid_lib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.framework.conf.conf_manager import ConfManager, get_conf_manager

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from app.util.logger import error_log, info_log


@dataclass
class ParsedInput:
    """
    Unified parsed input structure, used by SkillSearch / DataFetcher / SkillExecutor.

    Attributes:
        request_id:   Full-chain trace ID
        business_id:  Business identifier, e.g. "search", "ad"
        scene_id:     Scene identifier, 5 enumeration values (see module docs)
        context:      Key-value pairs extracted from request, for ${xxx} variable references in Skill data_sources
        source:       Request source, "alert" or "inspection"
        timestamp:    Event timestamp in seconds
        raw_data:     Original request dict, kept as fallback
    """
    request_id: str
    business_id: str
    biz_list: List[str]
    scene_id: str
    context: dict
    source: str
    timestamp: int
    raw_data: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# scene_id constants
# ─────────────────────────────────────────────────────────────

class SceneID:
    USABILITY_WARNING = "usability_warning"
    COREDUMP_WARNING  = "coredump_warning"
    BUSINESS_WARNING  = "business_warning"
    INSPECT   = "inspect"


# ─────────────────────────────────────────────────────────────
# Main parser
# ─────────────────────────────────────────────────────────────

class InputParser:
    """
    Unified input parser (thin adapter layer)
    """

    def __init__(self, biz_catalog_path: Optional[str] = None):
        self._node_id_to_biz: Dict[int, str] = {}
        self._owner_to_biz: Dict[str, str] = {}
        self._node_id_to_biz, self._owner_to_biz = self._load_biz_catalog()

    # ──────────────────────────────────────────
    # Business catalog mapping load
    # ──────────────────────────────────────────

    @staticmethod
    def _load_biz_catalog():
        """
        Read biz_catalog content from conf, parse YAML frontmatter, build mapping tables.
        On read failure, log error and return empty tables (degraded to "default", no impact on main flow).
        """
        node_id_map: Dict[int, str] = {}
        owner_map: Dict[str, str] = {}
        try:
            raw = get_conf_manager().get_string(ConfManager.KEY_BIZ_CATALOG)
            if not raw:
                error_log("input_parser: conf biz_catalog content is empty")
                return node_id_map, owner_map

            # Strip BOM / leading/trailing whitespace to avoid ^--- match failure
            raw = raw.lstrip("\ufeff").strip()

            # Extract frontmatter content (between --- lines, excluding --- lines themselves)
            # Use re.search + MULTILINE instead of re.match, tolerant of leading whitespace
            # Also tolerant of \r\n (Windows line endings)
            fm_body_match = re.compile(
                r"^---[ \t]*\r?\n(.*?)\r?\n---", re.DOTALL | re.MULTILINE
            ).search(raw)
            if not fm_body_match:
                error_log(f"input_parser: biz_catalog frontmatter missing, first 50 chars: {raw[:50]!r}")
                return node_id_map, owner_map

            fm_text = fm_body_match.group(1)

            # Parse with yaml.safe_load, supports arbitrary field order and no trailing newline
            import yaml as _yaml
            fm_dict = _yaml.safe_load(fm_body_match.group(1)) or {}
            biz_mapping = fm_dict.get("biz_mapping", {})
            if not isinstance(biz_mapping, dict):
                error_log("input_parser: biz_catalog biz_mapping format error")
                return node_id_map, owner_map

            for biz_id, block in biz_mapping.items():
                if not isinstance(block, dict):
                    continue
                # Build node_id -> biz_id mapping
                for node_id in (block.get("node_ids") or []):
                    try:
                        node_id_map[int(node_id)] = str(biz_id)
                    except (ValueError, TypeError):
                        pass
                # Build owner -> biz_id mapping
                for owner in (block.get("owners") or []):
                    if owner:
                        owner_map[str(owner)] = str(biz_id)

            info_log(f"input_parser: biz_catalog loaded, node_id {len(node_id_map)} entries, owner {len(owner_map)} entries")
        except Exception as e:
            error_log(f"input_parser: biz_catalog load failed: {e}")
        return node_id_map, owner_map

    # TODO: Replace this with your actual alert parsing logic.
    # The current implementation reads flat fields from a mock request JSON.
    # In production, extract fields from your real alert system's payload
    # (e.g., Prometheus AlertManager, PagerDuty, or internal alert platform),
    # and use _resolve_business_id() to derive biz_id from service metadata
    # instead of relying on the _mock_biz_id field.
    def parse_warning(self, data: dict, request_id: str = "") -> Optional[ParsedInput]:
        """
        Parse alert request, extract fields from flat JSON to construct ParsedInput.

        Request fields:
            _mock_biz_id    business identifier for Skill matching, default "demo"
            service_name    alert service name
            scene_type      scene type, e.g. "usability_warning"
            timestamp       alert timestamp (seconds)
            alert_rule_name alert rule name
            alert_level     alert severity level

        When integrating with a real alert system, implement the parsing logic here
        and use _resolve_business_id instead of _mock_biz_id.
        """
        request_id = request_id or self._gen_request_id()

        biz_id       = data.get("_mock_biz_id", "demo")
        service_name = data.get("service_name", "")
        scene_id     = data.get("scene_type", SceneID.USABILITY_WARNING)
        timestamp    = int(data.get("timestamp", 0)) or int(time.time())

        business_id = f"{biz_id}|{service_name}" if service_name else biz_id
        biz_list: List[str] = [biz_id] + ([service_name] if service_name else [])

        context = {
            "service_name":    service_name,
            "timestamp":       timestamp,
            "alert_rule_name": data.get("alert_rule_name", ""),
            "alert_level":     data.get("alert_level", ""),
            "scene_type":      scene_id,
            "request_id":      request_id,
        }

        info_log(f"[input_parser] Parse warning request — request_id=[{request_id}] biz_id=[{biz_id}] service_name=[{service_name}] scene_id=[{scene_id}]")

        return ParsedInput(
            request_id=request_id,
            business_id=business_id,
            biz_list=biz_list,
            scene_id=scene_id,
            context=context,
            source="warning",
            timestamp=timestamp,
            raw_data=data,
        )

    def parse_inspect(
        self,
        biz: str = "",
        rule_id: str = "",
        request_id: str = "",
        timestamp: Optional[int] = None,
    ) -> ParsedInput:
        """
        Parse inspection request
        """

        raise NotImplementedError("parse_inspect: implement your custom inspection request parsing interface.")

    def parse_release(
        self,
        data,
        request_id: str = ""
    ) -> ParsedInput:
        """
        Parse release/blocking scenario request
        """

        raise NotImplementedError("parse_release: implement your custom blocking request parsing interface.")

    # ──────────────────────────────────────────
    # Utility methods
    # ──────────────────────────────────────────

    def _resolve_business_id(self, service_name: str = "", kess: str = "") -> str:
        # Optionally integrate with a service registry to look up biz_id by service_name.
        # Currently returns "default" for all services.
        return "default"

    def reload_catalog(self, catalog_path: Optional[str] = None) -> None:
        node_id_map, owner_map = self._load_biz_catalog()
        self._node_id_to_biz = node_id_map
        self._owner_to_biz   = owner_map
        info_log(f"input_parser: reload_catalog done node_id={len(node_id_map)} owner={len(owner_map)}")

    @staticmethod
    def _gen_request_id() -> str:
        """Generate unique request_id"""
        return f"{int(time.time())}-{uuid_lib.uuid4().hex[:8]}"

# ─────────────────────────────────────────────────────────────
# Module-level singleton (needs to be initialized via init in skill_explore_main.py)
# ─────────────────────────────────────────────────────────────

_parser: Optional[InputParser] = None


def init_parser(biz_catalog_path: Optional[str] = None):
    """
    Initialize module-level parser (called once at service startup).

    Args:
        biz_catalog_path: path to biz_catalog.md, defaults to skill_memory/biz_catalog.md
    """
    global _parser
    _parser = InputParser(biz_catalog_path)


def get_parser() -> InputParser:
    """Get module-level parser instance; auto-initializes with empty config if not initialized"""
    global _parser
    if _parser is None:
        _parser = InputParser()
    return _parser