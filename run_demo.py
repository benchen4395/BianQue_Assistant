"""
本地直接运行 Demo，不依赖 Flask。

使用方式：
    cd bianqueSkill
    python run_demo.py

LLM 配置（二选一）：
    方式一：设置环境变量 LLM_API_BASE / LLM_API_KEY / LLM_MODEL
    方式二：取消下方注释并直接填写
"""

import json
import os
import sys

_SRC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "src"))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


def _configure_llm():
    # os.environ.setdefault("LLM_API_BASE", "https://api.openai.com/v1")
    # os.environ.setdefault("LLM_API_KEY",  "sk-your-api-key-here")
    # os.environ.setdefault("LLM_MODEL",    "gpt-4o")
    from app.framework.model.llm import OpenAICompatibleClient, set_llm_client
    set_llm_client(OpenAICompatibleClient())


def run_demo():
    _configure_llm()

    request_file = os.path.join(_SRC_DIR, "app", "framework", "data", "demo_data", "mock_alert_request.json")
    with open(request_file, "r", encoding="utf-8") as f:
        mock_data = json.load(f)

    print(f"\n告警请求:\n{json.dumps(mock_data, ensure_ascii=False, indent=2)}\n")

    from app.skill_explore.skill_explore_main import run_warning
    result = run_warning(data=mock_data)

    print(f"执行成功: {result.get('success')}")
    print(f"结论: {result.get('conclusion', '')}")

    choices = result.get("payload", {}).get("choices", [])
    if choices:
        content_str = choices[0].get("message", {}).get("content", "")
        try:
            print(f"\n完整输出:\n{json.dumps(json.loads(content_str), ensure_ascii=False, indent=2)}")
        except Exception:
            print(f"\n完整输出:\n{content_str}")

    return result


if __name__ == "__main__":
    run_demo()
