"""DeepSeek 模型层：薄客户端。

密钥来源（优先级从高到低）：页面里输入的运行时 key（只存本进程内存，重启即失效）
> 环境变量 DEEPSEEK_API_KEY。两者都不进代码/日志（红线 3）。
2026-09 实测可用模型：deepseek-flash（V4.1-Flash，带思考，effort 可调）。
_urlopen 单独命名，测试注入替身用。
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request

BASE_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_EFFORT = "low"
TIMEOUT_S = 60
PROBE_TIMEOUT_S = 20

_runtime_key: str | None = None
_key_lock = threading.Lock()


class LLMError(RuntimeError):
    """模型调用失败（网络/HTTP/响应结构），文案不含密钥。"""


def set_api_key(key: str | None) -> None:
    """设置/清除页面输入的运行时 key；只存内存，不落盘。"""
    global _runtime_key
    cleaned = (key or "").strip() or None
    with _key_lock:
        _runtime_key = cleaned


def api_key() -> str | None:
    with _key_lock:
        if _runtime_key:
            return _runtime_key
    return os.environ.get("DEEPSEEK_API_KEY")


def key_source() -> str | None:
    """override（页面输入）| env（环境变量）| None。"""
    with _key_lock:
        if _runtime_key:
            return "override"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "env"
    return None


def key_hint() -> str | None:
    """只回可展示的掩码：sk-…e151；没有 key 时 None。"""
    key = api_key()
    if not key:
        return None
    if len(key) <= 8:
        return "已配置"
    return f"{key[:3]}…{key[-4:]}"


def available() -> bool:
    return bool(api_key())


def _urlopen(req, timeout=None):
    return urllib.request.urlopen(req, timeout=timeout)


def _request(key: str, body: dict, *, timeout: float = TIMEOUT_S) -> dict:
    req = urllib.request.Request(
        BASE_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with _urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise LLMError(f"DeepSeek API HTTP {e.code}：{detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"DeepSeek API 连接失败：{e}") from None


def probe(key: str) -> None:
    """用一次最小调用验证 key；失败抛 LLMError，文案不含 key。"""
    key = (key or "").strip()
    if not key:
        raise LLMError("key 为空")
    payload = _request(key, {
        "model": os.environ.get("RECON_AGENT_MODEL", DEFAULT_MODEL),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "effort": DEFAULT_EFFORT,
    }, timeout=PROBE_TIMEOUT_S)
    if not payload.get("choices"):
        raise LLMError("DeepSeek API 响应结构异常：没有 choices")


def _post(body: dict) -> dict:
    key = api_key()
    if not key:
        raise LLMError(
            "未配置 DeepSeek key：可在页面右上角「模型」里输入，"
            "或设环境变量 DEEPSEEK_API_KEY")
    return _request(key, body)


def chat(messages: list[dict], max_tokens: int = 2000) -> str:
    payload = _post({
        "model": os.environ.get("RECON_AGENT_MODEL", DEFAULT_MODEL),
        "messages": messages,
        "max_tokens": max_tokens,
        "effort": os.environ.get("RECON_AGENT_EFFORT", DEFAULT_EFFORT),
    })
    try:
        return payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"DeepSeek API 响应结构异常：{str(payload)[:200]}") from None


def chat_with_tools(messages: list[dict], tools: list[dict],
                    max_tokens: int = 1200) -> dict:
    """一次带工具调用的模型往返；返回 content/tool_calls，不执行工具。

    tool_calls 统一成 [{id, name, arguments}]，arguments 始终是 JSON 字符串，
    方便上层用 Pydantic 解析。没有工具调用时列表为空，由循环判定失败。
    """
    payload = _post({
        "model": os.environ.get("RECON_AGENT_MODEL", DEFAULT_MODEL),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "effort": os.environ.get("RECON_AGENT_EFFORT", DEFAULT_EFFORT),
        "tools": tools,
        "tool_choice": "auto",
    })
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"DeepSeek API 响应结构异常：{str(payload)[:200]}") from None
    calls = []
    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments", "{}")
        calls.append({
            "id": call.get("id") or f"call_{i}",
            "name": fn.get("name") or "",
            "arguments": args if isinstance(args, str) else json.dumps(
                args, ensure_ascii=False),
        })
    return {
        "content": message.get("content") or "",
        "tool_calls": calls,
        "finish_reason": payload["choices"][0].get("finish_reason"),
    }
