"""
Skill MD Manager (conf-based storage)
Responsible for parsing, loading, creating, and partially updating all Skill files.
Storage backend: local config files managed by ConfManager.

Skill MD file format (fixed structure):
  ---
  name: ...
  description: ...
  version: ...
  tags: [...]
  ---

  ## Overview (optional)
  ...

  ---

  ## LoadDataSchema
  ```json
  [...]
  ```

  ---

  ## Prompt
  ```
  ...prompt text...
  ```

  ---

Storage mapping:
  each skill          -> conf key: skill_{name}  (STRING)
  skill registry      -> conf key: bianque_skill_registry (LIST_STRING)
  read/write entry    -> ConfManager (app.framework.conf.conf_manager)
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from app.framework.conf.conf_manager import ConfManager, get_conf_manager
from app.util.logger import error_log, info_log


class SkillParseError(Exception):
    """Skill MD file parse error"""


@dataclass
class SkillDoc:
    name: str
    description: str
    version: str = "1.0.0"
    business: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    raw_frontmatter: Dict[str, Any] = field(default_factory=dict)

    # LoadDataSchema section
    load_data_schema: List[Dict[str, Any]] = field(default_factory=list)

    # Prompt section
    prompt: str = ""

    # Metadata (in conf version, stores conf key instead of local file path)
    source_path: str = ""
    overview: str = ""


def _extract_code_block(text: str, lang: str = "") -> Optional[str]:
    """
    Extract the first code block from markdown text.
    When lang is "", matches any language (including unlabeled ``` blocks).
    Returns block content, or None if not found.
    """
    if lang:
        pattern = rf"```{re.escape(lang)}\s*\n(.*?)```"
    else:
        pattern = r"```(?:\w+)?\s*\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1)
    return None


def _split_sections(content: str) -> Dict[str, str]:
    """
    Split MD body (after frontmatter stripped) by top-level ## headings into {lower_title: body_text}.

    Key: ## headings inside code blocks (``` ... ```) are NOT used as section delimiters,
    to avoid incorrect truncation when Prompt blocks contain ## headings.
    """
    sections: Dict[str, str] = {}

    heading_positions: List[Tuple[int, int, str]] = []
    in_code_block = False
    i = 0
    while i < len(content):
        # Detect code block toggle (line-start ```)
        if content[i] == '`' and content[i:i+3] == '```':
            in_code_block = not in_code_block
            nl = content.find('\n', i)
            i = nl + 1 if nl >= 0 else len(content)
            continue
        # Only recognize ## headings outside code blocks
        if not in_code_block and content[i] == '#' and content[i:i+3] == '## ':
            is_line_start = (i == 0 or content[i - 1] == '\n')
            if is_line_start:
                nl = content.find('\n', i)
                line_end = nl if nl >= 0 else len(content)
                title = content[i+3:line_end].strip().lower()
                heading_positions.append((i, line_end + 1, title))
                i = line_end + 1
                continue
        i += 1

    for idx, (_, body_start, title) in enumerate(heading_positions):
        body_end = heading_positions[idx + 1][0] if idx + 1 < len(heading_positions) else len(content)
        sections[title] = content[body_start:body_end]

    return sections


def _parse_skill_md_from_content(content: str, source_key: str = "") -> SkillDoc:  # noqa: C901
    """
    Parse SkillDoc from MD string content (core parsing function for conf version).
    source_key is the corresponding conf key, stored in SkillDoc.source_path for log tracing.
    Raises SkillParseError on failure.
    """
    label = source_key or "<content>"

    fm_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    fm_match = fm_pattern.match(content)
    if not fm_match:
        raise SkillParseError(f"[{label}] missing YAML Frontmatter (--- block)")

    try:
        fm = yaml.safe_load(fm_match.group(1)) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(f"[{label}] Frontmatter YAML parse failed: {e}") from e

    name = fm.get("name", "")
    if not name:
        raise SkillParseError(f"[{label}] Frontmatter missing name field")

    description = fm.get("description", "")
    version = str(fm.get("version", "1.0.0"))
    business = fm.get("business", [])
    raw_tags = fm.get("tags", [])
    tags = list(raw_tags) if isinstance(raw_tags, (list, tuple)) else []

    body = content[fm_match.end():]
    sections = _split_sections(body)

    # Parse overview (optional)
    overview_raw = sections.get("overview", "")
    overview = re.sub(r"\n?---\n?", "", overview_raw).strip()

    # Parse LoadDataSchema
    schema_section = sections.get("loaddataschema", "")
    load_data_schema: List[Dict[str, Any]] = []
    if schema_section:
        json_text = _extract_code_block(schema_section, lang="json")
        if json_text is None:
            info_log(f"skill_md_manager: [{label}] LoadDataSchema json code block not found, using empty list")
        else:
            try:
                load_data_schema = json.loads(json_text)
            except json.JSONDecodeError as e:
                raise SkillParseError(
                    f"[{label}] LoadDataSchema JSON parse failed: {e}\nRaw text:\n{json_text}"
                ) from e
    else:
        info_log(f"skill_md_manager: [{label}] ## LoadDataSchema section not found")

    # Parse Prompt
    prompt_section = sections.get("prompt", "")
    prompt = ""
    if prompt_section:
        block = _extract_code_block(prompt_section, lang="")
        if block is None:
            info_log(f"skill_md_manager: [{label}] Prompt code block not found, prompt is empty")
        else:
            prompt = block
    else:
        info_log(f"skill_md_manager: [{label}] ## Prompt section not found")

    return SkillDoc(
        name=name,
        description=description,
        version=version,
        business=business,
        tags=tags,
        raw_frontmatter=fm,
        load_data_schema=load_data_schema,
        prompt=prompt,
        source_path=source_key,
        overview=overview,
    )


def _render_skill_md(skill: SkillDoc) -> str:
    """
    Render SkillDoc as standard MD text.
    """
    lines: List[str] = []

    # ── Frontmatter ───────────────────────────────────────────────────────────
    biz_lines = "[" + ", ".join(skill.business) + "]"
    tags_inline = "[" + ", ".join(skill.tags) + "]"
    lines.append("---")
    lines.append(f"name: {skill.name}")
    lines.append(f"description: {skill.description}")
    lines.append(f"version: {skill.version}")
    lines.append(f"business: {biz_lines}")
    lines.append(f"tags: {tags_inline}")
    lines.append("---")
    lines.append("")

    # ── Overview (optional) ──────────────────────────────────────────────────
    if skill.overview:
        lines.append("## Overview")
        lines.append("")
        lines.append(skill.overview)
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── LoadDataSchema ────────────────────────────────────────────────────────
    lines.append("## LoadDataSchema")
    lines.append("")
    lines.append("> The JSON below describes all data functions this Skill calls and their input schemas.")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(skill.load_data_schema, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Prompt ────────────────────────────────────────────────────────────────
    lines.append("## Prompt")
    lines.append("")
    lines.append("> The text below is injected into the conversation context when the Agent invokes this Skill, guiding the model to complete the task.")
    lines.append("")
    lines.append("```")
    prompt_body = skill.prompt if skill.prompt.endswith("\n") else skill.prompt + "\n"
    lines.append(prompt_body.rstrip("\n"))
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def load_all_skills() -> Dict[str, SkillDoc]:
    """
    Load all skills from the conf registry: fetch each skill MD content and parse it.
    Failed parses are logged and skipped, not blocking other skills.
    Returns {name: SkillDoc} dict.
    """
    mgr = get_conf_manager()
    skill_names = mgr.get_skill_registry()
    result: Dict[str, SkillDoc] = {}

    if not skill_names:
        info_log("skill_md_manager: load_all_skills — conf registry is empty, no Skills to load")
        return result

    for name in skill_names:
        content = mgr.get_skill_content(name)
        if content is None:
            error_log(f"skill_md_manager: load_all_skills — conf read failed [{name}], skip")
            continue
        if content.strip() == "# DELETED":
            info_log(f"skill_md_manager: load_all_skills — [{name}] marked deleted, skip")
            continue
        try:
            doc = _parse_skill_md_from_content(content, source_key=mgr.skill_key(name))
            if doc.name in result:
                info_log(
                    f"skill_md_manager: duplicate Skill name [{doc.name}], "
                    f"[{name}] overwrites previous entry"
                )
            result[doc.name] = doc
            info_log(f"skill_md_manager: loaded [{doc.name}] <- {mgr.skill_key(name)}")
        except SkillParseError as e:
            error_log(f"skill_md_manager: parse failed [{name}]: {e}")

    info_log(f"skill_md_manager: load_all_skills done, {len(result)} Skills loaded")
    return result


def add_skill(
    name: str,
    description: str,
    load_data_schema: List[Dict[str, Any]],
    prompt: str,
    version: str = "1.0.0",
    tags: Optional[List[str]] = None,
    overview: str = "",
    business: Optional[List[str]] = None,
) -> Tuple[str, SkillDoc]:
    """
    Generate new Skill MD text, write to conf, and register in registry.
    Raises FileExistsError if Skill name already exists (consistent with original interface semantics).
    Returns (conf_key, SkillDoc). SkillDoc can be written directly to memory cache without re-reading conf.
    """
    mgr = get_conf_manager()
    registry = mgr.get_skill_registry()
    if name in registry:
        # Check if it's a logically deleted placeholder — if so, allow re-creation
        existing = mgr.get_skill_content(name)
        if existing is None or existing.strip() != "# DELETED":
            raise FileExistsError(
                f"skill_md_manager: Skill [{name}] already exists in conf registry, "
                f"use update_skill to overwrite"
            )
        info_log(f"skill_md_manager: add_skill — [{name}] in deleted state, allowing re-creation")

    skill = SkillDoc(
        name=name,
        description=description,
        version=version,
        business=business or [],
        tags=tags or [],
        load_data_schema=load_data_schema,
        prompt=prompt,
        source_path=mgr.skill_key(name),
        overview=overview,
    )
    md_text = _render_skill_md(skill)

    ok = mgr.set_skill_content(name, md_text)
    if not ok:
        raise OSError(f"skill_md_manager: conf write skill [{name}] failed")

    mgr.register_skill(name)
    info_log(f"skill_md_manager: add_skill success [{name}] -> {mgr.skill_key(name)}")
    return mgr.skill_key(name), skill


def _bump_version(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except (ValueError, IndexError):
        return version + ".1"


def update_skill(
    name: str,
    *,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    overview: Optional[str] = None,
    prompt: Optional[str] = None,
    # ── Whole type operations ─────────────────────────────────────────────────
    schema_add_type: Optional[Dict[str, Any]] = None,
    schema_replace_type: Optional[Dict[str, Any]] = None,
    schema_remove_type: Union[str, Dict[str, Any], None] = None,
    # ── params_list sub-item operations ───────────────────────────────────────
    schema_add_param: Optional[Dict[str, Any]] = None,
    schema_add_param_type: Optional[str] = None,
    schema_update_param: Optional[Dict[str, Any]] = None,
    schema_update_param_type: Optional[str] = None,
    schema_remove_param_name: Optional[str] = None,
    schema_remove_param_type: Optional[str] = None,
    # ── In-memory SkillDoc passed by SkillManager (avoids re-reading conf) ────
    _cached_doc: Optional[SkillDoc] = None,
) -> Tuple[str, SkillDoc]:
    """
    Read Skill from conf (or memory cache) -> partially modify SkillDoc -> auto bump patch version -> write back to conf.
    Only explicitly passed parameters are modified; unset fields keep their original values.

    _cached_doc: in-memory cache object passed by SkillManager.update, preferred over conf read
                 to avoid stale reads under conf dir-mode local cache delay.

    Returns (conf_key, modified SkillDoc). SkillDoc can be written directly to memory cache without re-reading conf.

    ┌─────────────────────────────────────────────────────────────────┐
    │  LoadDataSchema Operations Quick Reference                       │
    ├──────────────────┬──────────────────────────────────────────────┤
    │  Whole type ops  │  schema_add_type      add whole type (dedup) │
    │                  │  schema_replace_type   replace whole type     │
    │                  │  schema_remove_type    delete whole type      │
    ├──────────────────┼──────────────────────────────────────────────┤
    │  params_list     │  schema_add_param + schema_add_param_type    │
    │  sub-item ops    │  schema_update_param + schema_update_param_type│
    │                  │  schema_remove_param_name + _remove_param_type│
    └──────────────────┴──────────────────────────────────────────────┘
    """
    mgr = get_conf_manager()
    # Prefer the in-memory cache object passed by caller (avoids conf dir-mode cache delay)
    if _cached_doc is not None:
        import copy
        skill = copy.deepcopy(_cached_doc)
        info_log(f"skill_md_manager: update_skill using in-memory cache [{name}]")
    else:
        content = mgr.get_skill_content(name)
        if content is None:
            raise FileNotFoundError(
                f"skill_md_manager: Skill [{name}] not found in conf "
                f"(key: {mgr.skill_key(name)})"
            )
        skill = _parse_skill_md_from_content(content, source_key=mgr.skill_key(name))

    # Basic field updates
    if description is not None:
        skill.description = description
    if tags is not None:
        skill.tags = tags
    if overview is not None:
        skill.overview = overview
    if prompt is not None:
        skill.prompt = prompt

    # LoadDataSchema operations
    schema = skill.load_data_schema

    # 1. Add whole type entry
    if schema_add_type is not None:
        add_type = schema_add_type.get("type")
        if any(e.get("type") == add_type for e in schema):
            info_log(f"skill_md_manager: schema_add_type — type [{add_type}] already exists, skip")
        else:
            schema.append(schema_add_type)
            info_log(f"skill_md_manager: schema_add_type success, type [{add_type}] appended")

    # 2. Replace whole type entry (auto-append if not found)
    if schema_replace_type is not None:
        target_type = schema_replace_type.get("type")
        replaced = False
        for entry in schema:
            if entry.get("type") == target_type:
                entry.clear()
                entry.update(schema_replace_type)
                replaced = True
                break
        if not replaced:
            schema.append(schema_replace_type)
            info_log(f"skill_md_manager: schema_replace_type — type [{target_type}] not found, appended")
        else:
            info_log(f"skill_md_manager: schema_replace_type — type [{target_type}] replaced")

    # 3. Remove whole type entry
    if schema_remove_type is not None:
        if isinstance(schema_remove_type, dict):
            remove_type_key = schema_remove_type.get("type", "")
        else:
            remove_type_key = schema_remove_type
        before_len = len(schema)
        schema = [e for e in schema if e.get("type") != remove_type_key]
        if len(schema) == before_len:
            info_log(f"skill_md_manager: schema_remove_type — type [{remove_type_key}] not found, no change")
        else:
            info_log(f"skill_md_manager: schema_remove_type — type [{remove_type_key}] removed")

    # 4. Add params_list sub-item
    if schema_add_param is not None and schema_add_param_type is not None:
        param_name = schema_add_param.get("name")
        _entry = next((e for e in schema if e.get("type") == schema_add_param_type), None)
        if _entry is None:
            error_log(f"skill_md_manager: schema_add_param — target type [{schema_add_param_type}] not found")
        else:
            params = _entry.setdefault("params_list", [])
            if any(p.get("name") == param_name for p in params):
                info_log(f"skill_md_manager: schema_add_param — name [{param_name}] already exists, skip")
            else:
                params.append(schema_add_param)
                info_log(f"skill_md_manager: schema_add_param — [{schema_add_param_type}].{param_name} added")

    # 5. Update params_list sub-item (full replace)
    if schema_update_param is not None and schema_update_param_type is not None:
        param_name = schema_update_param.get("name")
        _entry = next((e for e in schema if e.get("type") == schema_update_param_type), None)
        if _entry is None:
            error_log(f"skill_md_manager: schema_update_param — target type [{schema_update_param_type}] not found")
        else:
            params = _entry.get("params_list", [])
            for idx, p in enumerate(params):
                if p.get("name") == param_name:
                    params[idx] = schema_update_param
                    info_log(f"skill_md_manager: schema_update_param — [{schema_update_param_type}].{param_name} updated")
                    break
            else:
                params.append(schema_update_param)
                info_log(f"skill_md_manager: schema_update_param — [{schema_update_param_type}].{param_name} not found, appended")

    # 6. Remove params_list sub-item
    if schema_remove_param_name is not None and schema_remove_param_type is not None:
        _entry = next((e for e in schema if e.get("type") == schema_remove_param_type), None)
        if _entry is None:
            error_log(f"skill_md_manager: schema_remove_param — target type [{schema_remove_param_type}] not found")
        else:
            params = _entry.get("params_list", [])
            before = len(params)
            _entry["params_list"] = [p for p in params if p.get("name") != schema_remove_param_name]
            if len(_entry["params_list"]) == before:
                info_log(f"skill_md_manager: schema_remove_param — name [{schema_remove_param_name}] not found, no change")
            else:
                info_log(f"skill_md_manager: schema_remove_param — [{schema_remove_param_type}].{schema_remove_param_name} removed")

    skill.load_data_schema = schema
    skill.version = _bump_version(skill.version)

    md_text = _render_skill_md(skill)
    ok = mgr.set_skill_content(name, md_text)
    if not ok:
        raise OSError(f"skill_md_manager: conf write-back skill [{name}] failed")

    info_log(f"skill_md_manager: update_skill success [{name}] v{skill.version} -> {mgr.skill_key(name)}")
    return mgr.skill_key(name), skill


class SkillManager:
    """
    Skill manager singleton (conf-based storage).

    - On startup, SkillManager.instance() triggers load_all_skills() once,
      caching all Skills in memory.
    - add / update operations automatically sync memory cache after writing to conf;
      callers do not need to manually reload.
    """

    _inst: Optional["SkillManager"] = None

    def __init__(self) -> None:
        self._cache: Dict[str, SkillDoc] = {}
        self._reload()

    @classmethod
    def instance(cls) -> "SkillManager":
        """
        Return global singleton. Initializes and loads all skills on first call.
        """
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    # ─── Read operations ─────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[SkillDoc]:
        """Get SkillDoc by name, returns None if not found."""
        return self._cache.get(name)

    def all(self) -> Dict[str, SkillDoc]:
        """Return shallow copy of all loaded Skills."""
        return dict(self._cache)

    def names(self) -> List[str]:
        """Return list of all loaded Skill names."""
        return list(self._cache.keys())

    # ─── Write operations (conf + cache sync) ────────────────────────────────

    def add(
        self,
        name: str,
        description: str,
        load_data_schema: List[Dict[str, Any]],
        prompt: str,
        version: str = "1.0.0",
        tags: Optional[List[str]] = None,
        overview: str = "",
        business: Optional[List[str]] = None,
    ) -> str:
        """
        Create Skill: write to conf -> write constructed SkillDoc directly to memory cache.
        No re-read from conf (bypasses dir-mode local cache delay).
        Raises FileExistsError if Skill already exists (consistent with underlying add_skill).
        Returns the written conf key.
        """
        conf_key, doc = add_skill(
            name=name,
            description=description,
            load_data_schema=load_data_schema,
            prompt=prompt,
            version=version,
            tags=tags,
            overview=overview,
            business=business,
        )
        self._cache[doc.name] = doc
        info_log(f"SkillManager: cache synced (add) [{doc.name}]")
        return conf_key

    def update(
        self,
        name: str,
        *,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        overview: Optional[str] = None,
        prompt: Optional[str] = None,
        schema_add_type: Optional[Dict[str, Any]] = None,
        schema_replace_type: Optional[Dict[str, Any]] = None,
        schema_remove_type: Union[str, Dict[str, Any], None] = None,
        schema_add_param: Optional[Dict[str, Any]] = None,
        schema_add_param_type: Optional[str] = None,
        schema_update_param: Optional[Dict[str, Any]] = None,
        schema_update_param_type: Optional[str] = None,
        schema_remove_param_name: Optional[str] = None,
        schema_remove_param_type: Optional[str] = None,
    ) -> str:
        """
        Update Skill: write to conf -> sync memory cache.
        Parameters are identical to underlying update_skill.
        Returns the written conf key.
        """
        # Pass the in-memory SkillDoc to update_skill to avoid re-reading conf
        cached = self._cache.get(name)
        conf_key, doc = update_skill(
            name,
            description=description,
            tags=tags,
            overview=overview,
            prompt=prompt,
            schema_add_type=schema_add_type,
            schema_replace_type=schema_replace_type,
            schema_remove_type=schema_remove_type,
            schema_add_param=schema_add_param,
            schema_add_param_type=schema_add_param_type,
            schema_update_param=schema_update_param,
            schema_update_param_type=schema_update_param_type,
            schema_remove_param_name=schema_remove_param_name,
            schema_remove_param_type=schema_remove_param_type,
            _cached_doc=cached,
        )
        self._cache[doc.name] = doc
        info_log(f"SkillManager: cache synced (update) [{doc.name}]")
        return conf_key

    def delete(self, name: str) -> bool:
        """
        Delete Skill: clear conf content + unregister from registry + remove memory cache entry.
        conf has no delete API; logical deletion is done via empty content + registry unregister.
        Returns True idempotently when name does not exist.
        """
        mgr = get_conf_manager()
        ok = mgr.clear_skill_content(name)
        if ok:
            self._cache.pop(name, None)
            info_log(f"SkillManager: [{name}] deleted (conf cleared + registry unregistered + cache removed)")
        return ok

    def _reload(self) -> None:
        """Full reload of all Skills into cache."""
        self._cache = load_all_skills()
        info_log(f"SkillManager: cache refreshed, {len(self._cache)} Skills")

    def _sync_one(self, skill_name: str) -> None:
        """Pull a single skill from conf and update cache (used in _reload and other full-load scenarios)."""
        mgr = get_conf_manager()
        content = mgr.get_skill_content(skill_name)
        if content is None:
            error_log(f"SkillManager: conf read failed, cache sync skipped [{skill_name}]")
            return
        try:
            doc = _parse_skill_md_from_content(content, source_key=mgr.skill_key(skill_name))
            self._cache[doc.name] = doc
            info_log(f"SkillManager: cache synced [{doc.name}]")
        except SkillParseError as e:
            error_log(f"SkillManager: cache sync failed [{skill_name}]: {e}")


skill_md_manager = SkillManager.instance()

if __name__ == "__main__":
    # python3 -m app.skill_explore.skill_md_manager
    info_log(f"Loaded Skills: {skill_md_manager.names()}")

    doc = skill_md_manager.get("service-coredump-base-skill")
    if doc:
        info_log(f"get result -> name={doc.name}, version={doc.version}, tags={doc.tags}")
        info_log(f"source_path(conf key): {doc.source_path}")
    else:
        info_log("service-coredump-base-skill not found (conf cache not synced?)")