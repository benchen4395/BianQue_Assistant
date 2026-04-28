"""
LLM Unified Call Layer

This module is the sole entry point for system-LLM (large language model) interaction.

────────────────────────────────────────────────────────────
Custom integration (any LLM backend):
    Inherit BaseLLMClient and implement the chat() method, then call
        set_llm_client(MyLLMClient())
    After that, all global llm_call() invocations will use your implementation.

────────────────────────────────────────────────────────────
Public interface (for other modules to import):
    from app.framework.model.llm import llm_call

    result = llm_call(
        user_prompt  = "...",
        system_prompt= "...",   # optional
        request_id   = "...",   # optional, for log tracing
    )
────────────────────────────────────────────────────────────
"""

import os
from typing import Optional

from app.util.logger import error_log, info_log, save_prompt

# ─────────────────────────────────────────────────────────────────────────────
# Abstract base class: custom LLM clients should inherit this
# ─────────────────────────────────────────────────────────────────────────────


class BaseLLMClient:
    """
    LLM client abstract base class.

    Custom integration steps:
        1. Inherit BaseLLMClient
        2. Implement the chat() method
        3. Call set_llm_client(YourClient()) to register

    Example:
        class MyClient(BaseLLMClient):
            def chat(self, user_prompt, system_prompt="", request_id=""):
                # Call your own model API
                return my_api.call(system_prompt, user_prompt)

        set_llm_client(MyClient())
    """

    def chat(self, user_prompt: str, system_prompt: str = "", request_id: str = "") -> str:
        """
        Initiate a single chat request.

        Args:
            user_prompt:   user input prompt
            system_prompt: system prompt (may be empty)
            request_id:    trace ID (for logging)

        Returns:
            Model response text string; returns "Request failed!" on failure
        """
        raise NotImplementedError("Please implement BaseLLMClient.chat() method")


# ─────────────────────────────────────────────────────────────────────────────
# Built-in implementation: OpenAI-compatible API (configured via environment variables)
# ─────────────────────────────────────────────────────────────────────────────────────


class OpenAICompatibleClient(BaseLLMClient):
    """
    OpenAI-compatible API client.

    Configured via environment variables:
        LLM_API_BASE  — API Base URL (required)
        LLM_API_KEY   — API Key (required)
        LLM_MODEL     — Model name (default: qwen3)

    Dependency: pip install openai
    """

    def chat(self, user_prompt: str, system_prompt: str = "", request_id: str = "") -> str:
        import openai
        client = openai.OpenAI(
            base_url=os.environ["LLM_API_BASE"],
            api_key=os.environ["LLM_API_KEY"],
        )
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        resp = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL", "qwen3"),
            messages=messages,
        )
        return resp.choices[0].message.content or ""

# ─────────────────────────────────────────────────────────────────────────────
# Global client registration
# ─────────────────────────────────────────────────────────────────────────────

_llm_client: Optional[BaseLLMClient] = None


def set_llm_client(client: BaseLLMClient) -> None:
    """
    Register global LLM client.

    Args:
        client: instance of a BaseLLMClient subclass

    Example:
        from app.framework.model.llm import set_llm_client, OpenAICompatibleClient
        set_llm_client(OpenAICompatibleClient())
    """
    global _llm_client
    _llm_client = client
    info_log(f"[llm] Global LLM client registered: {type(client).__name__}")


def get_llm_client() -> BaseLLMClient:
    """
    Get the currently registered global LLM client.
    If not registered, returns an OpenAICompatibleClient instance (default implementation).
    """
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAICompatibleClient()
        info_log("[llm] Using default LLM client: OpenAICompatibleClient")
    return _llm_client


# ─────────────────────────────────────────────────────────────────────────────
# Public unified call interface
# ─────────────────────────────────────────────────────────────────────────────


def llm_call(
    user_prompt: str,
    system_prompt: str = "",
    request_id: str = "",
    need_save_prompt: bool = False,
) -> str:
    """
    Unified LLM call entry point (recommended interface).

    Args:
        user_prompt:      user input prompt
        system_prompt:    system prompt (may be empty)
        request_id:       trace ID (for logging)
        need_save_prompt: whether to save prompt to log file (for debugging)

    Returns:
        Model response text string; returns "Request failed!" on failure

    Example:
        from app.framework.model.llm import llm_call

        result = llm_call(
            user_prompt="Analyze the following alert: ...",
            system_prompt="You are a senior SRE engineer",
            request_id="req-123",
        )
    """
    if need_save_prompt:
        save_prompt(user_prompt, request_id)

    try:
        return get_llm_client().chat(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            request_id=request_id,
        )
    except NotImplementedError:
        raise
    except Exception as e:
        error_log(f"[llm] llm_call exception request_id={request_id}: {e}")
        return "Request failed!"