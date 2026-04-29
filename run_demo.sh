#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run_demo.sh — Run the BianQue Assistant demo locally (no Flask needed)
#
# Usage:
#   cd bianqueSkill
#   bash run_demo.sh
#
# LLM configuration (choose one):
#   Option A: export env vars before running this script
#   Option B: fill in the variables below directly
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── LLM environment variables ─────────────────────────────────────────────────
# Uncomment and fill in if not already set in your shell:
# export LLM_API_BASE="https://your-api-endpoint/v1"
# export LLM_API_KEY="your_api_key"
# export LLM_MODEL="your_model_name"

# Load from set_env.sh if it exists and env vars are not already set
if [ -z "$LLM_API_BASE" ] && [ -f "$SCRIPT_DIR/set_env.sh" ]; then
    echo "[run_demo] Loading LLM config from set_env.sh"
    source "$SCRIPT_DIR/set_env.sh"
fi

# Validate required env vars
if [ -z "$LLM_API_BASE" ] || [ -z "$LLM_API_KEY" ]; then
    echo "[run_demo] ERROR: LLM_API_BASE and LLM_API_KEY must be set."
    echo "  export LLM_API_BASE='https://your-api-endpoint/v1'"
    echo "  export LLM_API_KEY='your_api_key'"
    echo "  export LLM_MODEL='your_model_name'"
    exit 1
fi

echo "[run_demo] LLM_API_BASE=${LLM_API_BASE}"
echo "[run_demo] LLM_MODEL=${LLM_MODEL:-qwen3}"
echo ""

cd "$SCRIPT_DIR"
python3 run_demo.py
