"""Check onboarding live in Omnigent, on an empty copy of the record (never the real one): the interviewer,
in one chat, sends the native case finder to discover what it can reach and shows the person the list.

    PYTHONPATH=$PWD omnigent start --server "" --no-open
    python3 tests/check_onboarding_live.py
    omnigent stop

It needs Omnigent's client library; if this Python lacks it, the script restarts
itself under the Python that the installed omnigent command runs on.
"""

import asyncio
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from omnigent_client import OmnigentClient, SessionsChat
except ImportError:  # use the Python the omnigent command itself runs on, wherever it is installed
    import os
    launcher = shutil.which("omnigent")
    first = open(launcher, encoding="utf-8", errors="ignore").readline() if launcher else ""
    python = first[2:].strip() if first.startswith("#!") else ""
    if python and Path(python).exists() and Path(python).resolve() != Path(sys.executable).resolve():
        os.execv(python, [python, *sys.argv])
    raise SystemExit("Omnigent's client library is not available; install Omnigent first.")

from personal_assistant import build_agents  # noqa: E402
from personal_assistant.config import OMNIGENT_SERVER as SERVER, TEMPLATE_RECORD, WORKSPACE  # noqa: E402

OUT = WORKSPACE / "onboarding-live-check"


def tarball(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(directory.rglob("*")):
            tar.add(path, arcname=str(path.relative_to(directory)), recursive=False)
    return buffer.getvalue()


async def open_chat(client: OmnigentClient, bundle_dir: Path, harness: str, title: str) -> SessionsChat:  # noqa: ARG001
    """Create the session on this machine's registered host, which starts a runner for it."""
    async with httpx.AsyncClient(timeout=120) as http:
        hosts = (await http.get(f"{SERVER}/v1/hosts")).json()["hosts"]
        host = next((h for h in hosts if h.get("status") == "online"), None)
        if host is None:
            raise SystemExit("no online host; is `omnigent start` running?")
        metadata = {"title": title, "workspace": str(WORKSPACE), "host_id": host["host_id"]}
        resp = await http.post(f"{SERVER}/v1/sessions", data={"metadata": json.dumps(metadata)},
                               files={"bundle": ("agent.tar.gz", tarball(bundle_dir), "application/gzip")})
        resp.raise_for_status()
        session_id = resp.json()["session_id"]
    files = client.files.for_session(session_id)
    return SessionsChat(namespace=client.sessions, session=await client.sessions.get(session_id),
                        files_uploader=files.upload, files_getter=files.get)


async def turn(chat: SessionsChat, text: str, log: list, wait_for_children: bool = True) -> str:
    started = time.time()
    result = await chat.query(text)
    replies = [result.text]
    if wait_for_children:  # the chief ends its turn after dispatching; it is woken when workers finish
        deadline = time.time() + 1200
        while time.time() < deadline and await chat.tree_busy():
            await asyncio.sleep(10)
        try:
            later = await chat.await_turn(timeout=600)
            if later.text:
                replies.append(later.text)
        except Exception as error:  # no further turn is fine
            replies.append(f"(no wake-up turn: {type(error).__name__})")
    log.append({"sent": text, "replies": replies, "seconds": round(time.time() - started)})
    return replies[-1]

async def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(TEMPLATE_RECORD, OUT / "record", ignore=shutil.ignore_patterns(".git", "_*"))
    subprocess.run(["git", "init", "-q"], cwd=OUT / "record")
    build_agents.RECORD, build_agents.STATE, build_agents.AGENTS = OUT / "record", OUT / "state", OUT / "agents"
    build_agents.main()
    log: list = []
    async with OmnigentClient(base_url=SERVER) as client:
        chat = await open_chat(client, OUT / "agents" / "onboarding", "claude-sdk", "pa-onboarding-check")
        await turn(chat, "Hi, let's get me set up.", log)
    for entry in log:
        print(f"\n>> {entry['sent']} ({entry['seconds']}s)")
        for reply in entry["replies"]:
            print("  ", reply.replace("\n", "\n   "))


if __name__ == "__main__":
    asyncio.run(main())
