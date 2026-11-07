"""One isolated model call through the claude CLI.

Each call is a fresh session with no tools, no memory, no project files and
no settings, so the only things the model sees are the instructions and the
prompt passed here. The prompt goes in on stdin.
"""

import json
import os
import re
import subprocess
import tempfile

_EMPTY_DIR = tempfile.mkdtemp(prefix="pa-llm-")


def ask(prompt: str, *, system: str, model: str, timeout: int = 900) -> str:
    # no API key (the subscription is used) and no parent-session markers, so a nested launch is a fresh session
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED")}
    cmd = [
        "claude", "-p",
        "--model", model,
        "--safe-mode",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--tools", "",
        "--system-prompt", system,
        "--output-format", "text",
    ]
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                            timeout=timeout, env=env, cwd=_EMPTY_DIR)
    if result.returncode != 0:
        raise RuntimeError(f"{model} call failed: {result.stderr.strip()[-500:]}")
    return result.stdout.strip()


def ask_json(prompt: str, *, system: str, model: str, timeout: int = 900) -> dict:
    """Ask for JSON and parse the first object in the reply, retrying once."""
    for attempt in range(2):
        text = ask(prompt if attempt == 0 else prompt + "\n\nReply with the JSON object only.",
                   system=system, model=model, timeout=timeout)
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError(f"{model} did not return JSON: {text[:300]}")
