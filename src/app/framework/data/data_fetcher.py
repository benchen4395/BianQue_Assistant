"""
Data Fetcher — fetches all data sources in parallel based on SkillDoc.load_data_schema,
returns {type_key: result} dict.

Core flow:
    1. Iterate each entry in load_data_schema (grouped by type)
    2. For each entry's params_list, perform variable substitution (${xxx} -> context[xxx])
    3. When params_list is empty, call provider once with empty dict {} (provider relies entirely on context fallback)
    4. Call the registered function in data_provider_registry
    5. Execute in parallel; timeout/exception behavior controlled by required field
    6. Return {type_key: result_or_None}

Variable substitution rules (${xxx} placeholders):
    - Scope: all string/list[str] field values within params_list
    - Source: ParsedInput.context dict
    - Missing: keep original placeholder string and log a warning

Result structure:
    {
        "coredump_stack": <data or None>,
        "change_event":   <data or None>,
        ...
    }
    If a required=True data source fails, raises FetchAbortError.
"""

import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional

from app.framework.data.data_provider_registry import get_provider, get_data_lake_catalog
from app.skill_explore.skill_md_manager import SkillDoc
from app.skill_explore.input_parser import ParsedInput
from app.util.logger import error_log, info_log


def _get_type_description(type_key: str) -> str:
    """
    Get the description field for a given type from data_lake.yaml, for log identification.
    Returns type_key itself if not found.
    """
    catalog = get_data_lake_catalog()
    for cap in catalog.get("capabilities", []):
        if cap.get("type") == type_key:
            return cap.get("description", type_key)
    return type_key

# Max wait time per data source (seconds)
_DATA_FETCH_TIMEOUT_SECONDS = 30

# Max parallel thread count
_MAX_WORKERS = 8


class FetchAbortError(Exception):
    """Raised when a required=True data source fetch fails, aborting subsequent Workflow execution."""


# ─────────────────────────────────────────────────────────────────────────────
# Variable substitution
# ─────────────────────────────────────────────────────────────────────────────

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _replace_vars_in_value(value, context) -> Any:
    """
    Recursively replace ${xxx} placeholders in value.
    Supports str / list / dict container types; others returned unchanged.
    """
    if isinstance(value, str):
        def _replacer(m) -> str:
            key = m.group(1)
            if key in context:
                return str(context[key])
            info_log(f"data_fetcher: variable substitution missing key=[{key}], keeping original placeholder")
            return m.group(0)
        return _VAR_PATTERN.sub(_replacer, value)
    elif isinstance(value, list):
        return [_replace_vars_in_value(item, context) for item in value]
    elif isinstance(value, dict):
        return {k: _replace_vars_in_value(v, context) for k, v in value.items()}
    return value


def _resolve_params(params, context):
    """Perform full variable substitution on a single param dict, return new dict."""
    return {k: _replace_vars_in_value(v, context) for k, v in params.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Single entry fetch
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_one_entry(entry, context, request_id) :
    """
    Fetch data for a single LoadDataSchema entry.
    Entry format: {"type": "coredump_stack", "params_list": [...]}

    Return rules:
      - params_list non-empty: call provider for each param, return equal-length result list
      - params_list empty: call provider once with empty dict {} (provider relies entirely on context fallback),
        return single-element list
    """
    type_key = entry.get("type", "")
    params_list = entry.get("params_list", [])
    type_desc = _get_type_description(type_key)

    provider = get_provider(type_key)
    if provider is None:
        info_log(f"data_fetcher: [{request_id}] provider not found for type=[{type_key}], skip")
        return None

    # When params_list is empty, call with empty dict once so provider relies entirely on context fallback
    effective_params = params_list if params_list else [{}]

    results = []
    for param in effective_params:
        resolved = _resolve_params(param, context)
        try:
            result = provider(resolved, context)
            results.append(result)
        except Exception:
            required = param.get("required", False)
            error_log(
                f"data_fetcher: [{request_id}] type=[{type_key}]({type_desc})"
                f" fetch failed, required={required}\n"
                + traceback.format_exc()
            )
            if required:
                raise FetchAbortError(
                    f"Required data source fetch failed: type={type_key}({type_desc})"
                )
            results.append(None)

    return results


# ─────────────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────────────

def fetch_all_data(
    skill: SkillDoc,
    parsed_input: ParsedInput,
) -> Dict[str, Any]:
    """
    Fetch all data sources in skill.load_data_schema in parallel.

    Args:
        skill        : loaded SkillDoc object
        parsed_input : request context parsed by input_parser

    Returns:
        {type_key: result_or_None} dict.
        result being None means the type fetch failed (required=False) or provider not registered.

    Raises:
        FetchAbortError: raised when any required=True data source fetch fails, aborting Workflow.
    """
    request_id = parsed_input.request_id
    context = parsed_input.context
    schema = skill.load_data_schema

    if not schema:
        info_log(f"data_fetcher: [{request_id}] load_data_schema is empty, returning empty result directly")
        return {}

    results: Dict[str, Any] = {}
    abort_error: Optional[FetchAbortError] = None

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(schema))) as pool:
        future_to_type = {
            pool.submit(_fetch_one_entry, entry, context, request_id): entry.get("type", "")
            for entry in schema
        }

        for future in as_completed(future_to_type, timeout=_DATA_FETCH_TIMEOUT_SECONDS):
            type_key = future_to_type[future]
            try:
                results[type_key] = future.result()
                info_log(f"data_fetcher: [{request_id}] type=[{type_key}] fetch complete")
            except FetchAbortError as e:
                # Log and wait for remaining tasks, then raise unified error
                abort_error = e
                error_log(f"data_fetcher: [{request_id}] FetchAbortError: {e}")
            except FuturesTimeoutError:
                error_log(f"data_fetcher: [{request_id}] type=[{type_key}] timeout")
                results[type_key] = None
            except Exception:
                error_log(
                    f"data_fetcher: [{request_id}] type=[{type_key}] unexpected exception\n"
                    + traceback.format_exc()
                )
                results[type_key] = None

    if abort_error is not None:
        raise abort_error

    info_log(f"data_fetcher: [{request_id}] all data sources fetched, types={list(results.keys())}")
    return results