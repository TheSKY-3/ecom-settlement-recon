"""审计链：每步记录输入/输出指纹并环环相扣（哈希含上一步哈希），篡改任何一环即断链。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ZERO = "0" * 64


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _digest(payload: dict, prev_hash: str) -> str:
    blob = json.dumps({**payload, "prev_hash": prev_hash}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class AuditChain:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.steps: list[dict] = []

    def add_step(self, action: str, inputs: list | None = None,
                 outputs: list | None = None, params: dict | None = None) -> None:
        payload = {"seq": len(self.steps) + 1, "action": action,
                   "inputs": inputs or [], "outputs": outputs or [], "params": params or {}}
        prev = self.steps[-1]["step_hash"] if self.steps else ZERO
        self.steps.append({**payload, "prev_hash": prev, "step_hash": _digest(payload, prev)})

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, "steps": self.steps,
                "chain_hash": self.steps[-1]["step_hash"] if self.steps else ZERO}


def verify_chain(chain: dict) -> bool:
    prev = ZERO
    for step in chain["steps"]:
        payload = {k: step[k] for k in ("seq", "action", "inputs", "outputs", "params")}
        if step["prev_hash"] != prev or _digest(payload, prev) != step["step_hash"]:
            return False
        prev = step["step_hash"]
    return chain.get("chain_hash") == prev
