"""Minimal OpenAI-compatible Chat Completions client."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class JudgeConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 120.0
    max_tokens: int = 3072
    temperature: float = 0.0

    @classmethod
    def from_args(
        cls,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float,
        max_tokens: int,
        temperature: float,
    ) -> "JudgeConfig":
        key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        return cls(
            base_url=base_url.rstrip("/"),
            api_key=key,
            model=model,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
        )


def _openai_chat_completion(
    messages: list[dict[str, Any]], config: JudgeConfig
) -> str | None:
    url = config.base_url
    if not url.endswith("/chat/completions"):
        if not url.endswith("/v1"):
            url += "/v1"
        url += "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    payload = {
        "model": config.model,
        "messages": messages,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=config.timeout)
    response.raise_for_status()
    body = response.json()
    choice = body["choices"][0]
    if choice.get("finish_reason") not in (None, "stop"):
        return None
    return choice["message"]["content"]


def chat_completion(messages: list[dict[str, Any]], config: JudgeConfig) -> str | None:
    return _openai_chat_completion(messages, config)


def call_with_transport_retries(
    messages: list[dict[str, Any]],
    config: JudgeConfig,
    *,
    retries: int,
    retry_delay: float,
) -> str | None:
    """Retry transport/API errors; response-format retries are handled by callers."""
    for attempt in range(retries):
        try:
            return chat_completion(messages, config)
        except Exception as exc:
            if attempt + 1 == retries:
                print(f"[judge] request failed after {retries} attempts: {exc}")
                return None
            time.sleep(retry_delay)
    return None
