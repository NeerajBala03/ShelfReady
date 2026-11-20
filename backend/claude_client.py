"""
ShelfReady — Claude client over the Claude CLI (NO API KEY).

This is the project's defining choice: instead of calling the Anthropic API with
a secret key, ShelfReady shells out to the local `claude` CLI in headless mode
(`claude -p ... --output-format json`). It uses the operator's existing Claude
login, so the whole pipeline runs with zero key management — ideal for a
hackathon machine and for air-gapped review stations that already have Claude.

Design:
  * `available()`            — is the CLI installed and runnable?
  * `complete(prompt, ...)`  — run one headless turn, return (text, meta).
  * `complete_json(...)`     — same, but parse the model's reply as JSON
                               (tolerates ```json fences).

Every call returns a `meta` dict with cost_usd + token counts pulled straight
from the CLI's own telemetry, so ShelfReady can report true cost-per-listing.

If the CLI is missing or errors, callers fall back to the deterministic offline
engine in generator.py — the demo therefore NEVER breaks for a judge.
"""
from __future__ import annotations
import json, os, shutil, subprocess, time

CLI = os.environ.get("SHELFREADY_CLAUDE_BIN", "claude")
DEFAULT_TIMEOUT = int(os.environ.get("SHELFREADY_CLAUDE_TIMEOUT", "120"))


def available() -> bool:
    """True if the claude CLI binary is on PATH."""
    return shutil.which(CLI) is not None


def _extract_json(text: str):
    """Pull a JSON object out of a model reply, tolerating markdown fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    # find the first {...} or [...] span
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = t.find(opener), t.rfind(closer)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    return json.loads(t)  # last resort, will raise if truly not JSON


def complete(prompt: str, system: str | None = None,
             timeout: int = DEFAULT_TIMEOUT) -> tuple[str, dict]:
    """Run one headless Claude turn. Returns (reply_text, meta)."""
    cmd = [CLI, "-p", prompt, "--output-format", "json"]
    if system:
        cmd += ["--append-system-prompt", system]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({proc.returncode}): {proc.stderr[:400]}")
    payload = json.loads(proc.stdout)
    usage = payload.get("usage", {}) or {}
    meta = {
        "engine": "claude-cli",
        "model": (payload.get("modelUsage") and next(iter(payload["modelUsage"])))
                 or payload.get("model") or "claude",
        "cost_usd": payload.get("total_cost_usd", 0.0),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "wall_ms": int((time.time() - t0) * 1000),
        "session_id": payload.get("session_id"),
    }
    return payload.get("result", ""), meta


def complete_json(prompt: str, system: str | None = None,
                  timeout: int = DEFAULT_TIMEOUT) -> tuple[dict, dict]:
    text, meta = complete(prompt, system=system, timeout=timeout)
    return _extract_json(text), meta


if __name__ == "__main__":
    print("claude CLI available:", available())
    if available():
        out, meta = complete_json(
            'Return only this JSON: {"status":"ready","product":"ShelfReady"}')
        print("reply:", out)
        print("meta:", {k: meta[k] for k in ("model", "cost_usd", "wall_ms")})
