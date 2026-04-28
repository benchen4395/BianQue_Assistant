"""
ConfManager — unified config storage entry for the Skill system.

Key naming conventions:
    bianque_skill_biz_classify        — biz_catalog content
    bianque_skill_data_lake_summary   — data_lake_summary content
    skill_{skill_name}                — individual skill markdown text
    bianque_skill_registry            — list of all registered skill names
"""

import json
import os
from typing import List, Optional, Set

from app.util.logger import error_log, info_log


_DEFAULT_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "local_config")


class ConfManager:
    """
    Skill system config storage manager — local filesystem implementation.

    All Skill files and registry entries are stored as text files under base_dir.
    File naming: {key}.txt

    Default storage path: src/app/local_config
    """

    # ─── Key constants ────────────────────────────────────────────────────────
    KEY_BIZ_CATALOG            = "bianque_skill_biz_classify"
    KEY_DATA_LAKE              = "bianque_skill_data_lake_summary"
    KEY_SKILL_REGISTRY         = "bianque_skill_registry"
    KEY_SKILL_PREFIX           = "skill_"
    KEY_STAGE2_PROMPT_PREFIX   = "bianque_stage2_prompt_"

    def __init__(self, base_dir: str = "") -> None:
        if base_dir == "":
            base_dir = os.path.normpath(_DEFAULT_BASE_DIR)

        self._base_dir = base_dir
        os.makedirs(self._base_dir, exist_ok=True)
        self._token = "local_token_placeholder"
        self._registry_cache: List[str] = self._load_registry_from_local()
        info_log(
            f"LocalConfManager: initialized, storage dir={self._base_dir}, "
            f"registry loaded ({len(self._registry_cache)} entries)"
        )

    def _get_file_path(self, key: str) -> str:
        return os.path.join(self._base_dir, f"{key}.txt")

    def _load_registry_from_local(self) -> List[str]:
        try:
            return list(self.get_list(self.KEY_SKILL_REGISTRY))
        except Exception as e:
            error_log(f"LocalConfManager._load_registry_from_local: error={e}")
            return []

    # ─── STRING read/write ────────────────────────────────────────────────────

    def get_string(self, key: str) -> Optional[str]:
        path = self._get_file_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                if content == "# DELETED":
                    return None
                return content
        except Exception as e:
            error_log(f"LocalConfManager.get_string: read failed key=[{key}] error={e}")
            return None

    def set_string(self, key: str, value: str, description: str = "") -> bool:
        path = self._get_file_path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(value)
            info_log(f"LocalConfManager.set_string: write success key=[{key}]")
            return True
        except Exception as e:
            error_log(f"LocalConfManager.set_string: write failed key=[{key}] error={e}")
            return False

    # ─── LIST_STRING / registry read/write ───────────────────────────────────

    def _flush_registry(self) -> bool:
        path = self._get_file_path(self.KEY_SKILL_REGISTRY)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(self._registry_cache, ensure_ascii=False))
            info_log(f"LocalConfManager._flush_registry: persisted {len(self._registry_cache)} entries")
            return True
        except Exception as e:
            error_log(f"LocalConfManager._flush_registry: persist failed error={e}")
            return False

    def get_list(self, key: str) -> List[str]:
        path = self._get_file_path(key)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                return json.loads(content)
        except Exception as e:
            error_log(f"LocalConfManager.get_list: read failed key=[{key}] error={e}")
            return []

    # ─── Skill convenience methods ────────────────────────────────────────────

    def skill_key(self, skill_name: str) -> str:
        return f"{self.KEY_SKILL_PREFIX}{skill_name}"

    def get_skill_content(self, skill_name: str) -> Optional[str]:
        return self.get_string(self.skill_key(skill_name))

    def set_skill_content(self, skill_name: str, content: str) -> bool:
        return self.set_string(
            self.skill_key(skill_name),
            content,
            description=f"bianque skill: {skill_name}",
        )

    def clear_skill_content(self, skill_name: str) -> bool:
        """Mark skill content as deleted and unregister it. Returns True on success."""
        key = self.skill_key(skill_name)
        path = self._get_file_path(key)
        if os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("# DELETED")
                info_log(f"LocalConfManager.clear_skill_content: marked deleted key=[{key}]")
            except Exception as e:
                error_log(f"LocalConfManager.clear_skill_content: update failed key=[{key}] error={e}")
                return False
        else:
            info_log(f"LocalConfManager.clear_skill_content: key=[{key}] not found, skip")

        ok = self.unregister_skill(skill_name)
        if ok:
            info_log(f"LocalConfManager.clear_skill_content: [{skill_name}] removed from registry")
        return ok

    def get_skill_registry(self) -> Set[str]:
        return set(self._registry_cache)

    def register_skill(self, skill_name: str) -> bool:
        """Add skill_name to registry (idempotent). Syncs memory cache and local file."""
        if skill_name in self._registry_cache:
            info_log(f"LocalConfManager.register_skill: [{skill_name}] already exists, skip")
            return True
        self._registry_cache.append(skill_name)
        ok = self._flush_registry()
        if not ok:
            self._registry_cache.remove(skill_name)
        return ok

    def unregister_skill(self, skill_name: str) -> bool:
        """Remove skill_name from registry (idempotent). Syncs memory cache and local file."""
        if skill_name not in self._registry_cache:
            info_log(f"LocalConfManager.unregister_skill: [{skill_name}] not in registry, skip")
            return True
        self._registry_cache.remove(skill_name)
        ok = self._flush_registry()
        if not ok:
            self._registry_cache.append(skill_name)
        return ok


# ─── Process-level singleton ──────────────────────────────────────────────────

_conf_manager_instance: Optional[ConfManager] = None

def get_conf_manager() -> ConfManager:
    """Return the process-level ConfManager singleton. Initializes on first call."""
    global _conf_manager_instance
    if _conf_manager_instance is None:
        _conf_manager_instance = ConfManager()
    return _conf_manager_instance
