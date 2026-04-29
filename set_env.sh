#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# set_env.sh — LLM environment variable configuration
#
# Usage:
#   source set_env.sh
#   (or loaded automatically by run_demo.sh / run_flask.sh)
#
# Fill in your own LLM API credentials below.
# ─────────────────────────────────────────────────────────────────────────────

export LLM_API_BASE="https://your-api-endpoint/v1"
export LLM_API_KEY="your_api_key"
export LLM_MODEL="your_model_name"
