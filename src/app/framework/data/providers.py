"""
Data Providers — implementation of data fetch functions, each corresponding to a capability in data_lake.yaml.
To add a new provider: implement the function here, register it in data_lake.yaml, then restart the service.
"""

from typing import Any
import os


# TODO: Replace _fetch_data_demo with your actual data source implementation.
# This demo reads from a local JSON file for demonstration purposes.
# In production, call your monitoring system, metrics API, or database here.
# The function signature must stay the same: (params: dict, context: dict) -> Any
def _fetch_data_demo(params: dict, context: dict) -> Any:
    """Demo provider — reads service performance data from demo_data/performance.json, filtered by service_name."""
    import json as _json

    service_name = params.get("service_name", "") or context.get("service_name", "")
    perf_file = os.path.join(os.path.dirname(__file__), "demo_data", "performance.json")
    try:
        with open(perf_file, "r", encoding="utf-8") as f:
            all_data = _json.load(f)
    except Exception:
        return {}

    if service_name and service_name in all_data:
        return {service_name: all_data[service_name]}
    return all_data
