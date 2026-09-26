"""两出口公共小循环：事实收集(外部) → 模型 → 白名单校验 → 重试/降级 + 留痕。

预算：模型往返 ≤ max_attempts(默认 2，初答+重试)；API 错误不重试直接降级。
留痕：每次调用一行 JSON 到 RECON_AGENT_DIR/trace.jsonl（默认 output/agent/，
已 gitignore）。记录绝不含密钥。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from src.agent import guardrails, llm, prompts

MAX_ATTEMPTS = 2


def _trace_dir() -> Path:
    return Path(os.environ.get(
        "RECON_AGENT_DIR",
        Path(__file__).resolve().parents[2] / "output" / "agent"))


def _append_trace(record: dict) -> None:
    d = _trace_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _refs(facts: dict) -> list[str]:
    out = []
    f, g = facts.get("finding"), facts.get("gt")
    if f:
        out.append(f["finding_id"])
    if g:
        out.append(g["gt_id"])
    if facts.get("order_id"):
        out.append(facts["order_id"])
    return out


def run_once(kind: str, ref: str, question: str, facts: dict,
             fallback_answer: str, max_attempts: int = MAX_ATTEMPTS) -> dict:
    facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    facts_hash = hashlib.sha256(facts_json.encode("utf-8")).hexdigest()[:16]
    base = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind,
            "ref": ref, "facts_sha256": facts_hash,
            "model": os.environ.get("RECON_AGENT_MODEL", llm.DEFAULT_MODEL)}

    def finish(source: str, answer: str, reason: str, attempts: list) -> dict:
        _append_trace({**base, "source": source, "reason": reason,
                       "attempts": attempts})
        return {"answer": answer, "source": source, "refs": _refs(facts),
                "facts_sha256": facts_hash}

    if not llm.available():
        return finish("fallback", fallback_answer, "no_key", [])

    user_msg = f"事实单 JSON：\n{prompts.facts_json(facts)}\n\n任务：{question}"
    attempts: list = []
    for i in range(max_attempts):
        try:
            text = llm.chat([{"role": "system", "content": prompts.SYSTEM_PROMPT},
                             {"role": "user", "content": user_msg}])
        except llm.LLMError as e:
            attempts.append({"error": str(e)})
            return finish("fallback", fallback_answer, "llm_error", attempts)
        check = guardrails.check(text, facts)
        attempts.append({"check": check})
        if check["ok"]:
            return finish("llm", text, "ok", attempts)
        user_msg += (
            "\n\n你上一轮的回答包含事实单中不存在的数字或编号："
            f"{json.dumps(check, ensure_ascii=False)}。"
            "请只用事实单中的信息重写。")
    return finish("fallback", fallback_answer, "guardrail", attempts)
