"""Run one turn of an agent through the claude CLI, with its tool server.

This is how the builder is run from inside the chief of staff's tools, and how
the test harness runs every agent. The agent gets its instructions, its role's
tools on the tool server, and nothing else: no built-in tools, no project
files, no settings. Passing a session id continues that conversation.
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

from system import prompts
from system.config import MODELS, ROOT
from system.record import Record

SERVER = ROOT / "system" / "tools_server.py"


def mcp_config(role: str, record_dir: Path, state: Path, today: str | None) -> dict:
    args = [str(SERVER), "--role", role, "--record", str(record_dir), "--state", str(state)]
    if today:
        args += ["--today", today]
    return {"mcpServers": {"pa": {"command": sys.executable, "args": args}}}


def run_agent(role: str, record_dir: Path, state: Path, message: str, *, today: str | None = None,
              session: str | None = None, timeout: int = 1800) -> dict:
    record_dir, state = Path(record_dir).resolve(), Path(state).resolve()
    state.mkdir(parents=True, exist_ok=True)
    rec = Record(record_dir, date.fromisoformat(today) if today else None)
    config_path = state / f"mcp-{role}.json"
    config_path.write_text(json.dumps(mcp_config(role, record_dir, state, today)), encoding="utf-8")

    new = session is None
    session = session or str(uuid.uuid4())
    cmd = [
        "claude", "-p",
        "--model", MODELS[role],
        "--system-prompt", prompts.build(role, rec),
        "--mcp-config", str(config_path),
        "--strict-mcp-config",
        "--disable-slash-commands",       # no skills or commands from this machine
        "--setting-sources", "project",   # the empty workdir: no user hooks, plugins or settings
        "--tools", "",
        "--allowedTools", "mcp__pa",
        "--output-format", "json",
    ]
    cmd += ["--session-id", session] if new else ["--resume", session]
    # no API key (the subscription is used) and no parent-session markers, so a nested launch is a fresh session
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED")}
    env["MCP_TOOL_TIMEOUT"] = "1500000"
    env["MAX_MCP_OUTPUT_TOKENS"] = "60000"  # a decision report or a weekly review is long; it must reach the agent whole
    workdir = state / "workdir"
    workdir.mkdir(exist_ok=True)
    result = subprocess.run(cmd, input=message, capture_output=True, text=True, timeout=timeout, env=env, cwd=workdir)
    try:
        out = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"{role} turn failed: {result.stderr.strip()[-800:] or result.stdout[-800:]}")
    return {"text": out.get("result", ""), "session": session, "is_error": out.get("is_error", False),
            "cost_usd": out.get("total_cost_usd"), "turns": out.get("num_turns")}
