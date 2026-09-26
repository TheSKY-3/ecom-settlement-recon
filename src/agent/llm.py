"""DeepSeek 模型层：薄客户端。

密钥只读环境变量 DEEPSEEK_API_KEY，不进代码/日志（红线 3）。
2026-09 实测可用模型：deepseek-flash（V4.1-Flash，带思考，effort 可调）。
_urlopen 单独命名，测试注入替身用。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_EFFORT = "low"
TIMEOUT_S = 60


class LLMError(RuntimeError):
    """模型调用失败（网络/HTTP/响应结构），文案不含密钥。"""


def available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def _urlopen(req, timeout=None):
    return urllib.request.urlopen(req, timeout=timeout)


def chat(messages: list[dict], max_tokens: int = 2000) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise LLMError("环境变量 DEEPSEEK_API_KEY 未设置")
    body = {
        "model": os.environ.get("RECON_AGENT_MODEL", DEFAULT_MODEL),
        "messages": messages,
        "max_tokens": max_tokens,
        "effort": os.environ.get("RECON_AGENT_EFFORT", DEFAULT_EFFORT),
    }
    req = urllib.request.Request(
        BASE_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with _urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise LLMError(f"DeepSeek API HTTP {e.code}：{detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"DeepSeek API 连接失败：{e}") from None
    try:
        return payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"DeepSeek API 响应结构异常：{str(payload)[:200]}") from None
