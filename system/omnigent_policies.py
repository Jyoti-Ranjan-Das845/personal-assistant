"""Omnigent policies that guard the native worker.

The worker is native Claude Code, so it has the person's connectors, the web,
a shell and file tools. Omnigent installs Claude Code hooks in every native
session that send each tool call here before it runs, and a failed check
denies the call. These rules are therefore enforced in code, not in the
worker's instructions:

- Reading the person's apps is allowed, and so are drafts in them.
- Anything that acts in an app (send, reply, book, post, share, edit) waits
  for the person's yes (ASK). Deleting is denied.
- Once a session has read private data from the person's apps, it may not
  reach the web, so nothing private can leave through a search or a fetch.
  Research that needs the web runs in a fresh session.
- Browser control and scripts that drive Mail or Messages are denied: they
  could act as the person without passing any of the checks above.
- Files: a native agent may write only in its own workspace and the record's
  inbox, and may read only there, in the person's Claude and Codex
  conversation stores, in the kit (for the constitution), and in folders the
  person has allowed (PA_READABLE). Secret stores such as ~/.ssh are denied
  outright, and shell commands are held to the same folders. Reading the
  person's private data, their stores, the inbox or an allowed folder, marks
  the session, exactly like reading their mail.

Omnigent imports this module by its dotted path, so the project root must be
on the Omnigent server's and runner's Python path.

    guardrails:
      policies:
        worker_guard:
          type: function
          on: [tool_call]
          function:
            path: system.omnigent_policies.worker_guard
            arguments: {project_root: /path/to/personal-assistant}
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

ALLOW = {"result": "ALLOW"}
TAINT_KEY = "pa_worker_read_private"

READ_VERBS = ("get", "list", "search", "read", "query", "fetch", "download", "find", "lookup", "view",
              "describe", "export", "whoami", "suggest_time", "metadata", "permissions", "status", "help")
DRAFT_VERBS = ("create_draft", "update_draft", "draft")
DESTRUCTIVE_VERBS = ("delete", "trash", "remove", "purge", "empty", "destroy", "wipe")

WEB_TOOLS = {"WebSearch", "WebFetch"}
BROWSER_PREFIXES = ("mcp__claude-in-chrome__", "mcp__Claude_Browser__", "mcp__computer-use__", "mcp__playwright")
FILE_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
FILE_READ_TOOLS = {"Read", "Glob", "Grep", "NotebookRead"}
SHELL_TOOLS = {"Bash", "sys_os_shell"}

PRIVATE_STORES = re.compile(r"(/\.claude/projects|/\.codex/|/Library/Messages|/\.omnigent/|~/\.claude|~/\.codex)")
SECRETS = re.compile(r"(\.ssh\b|\.gnupg|\.aws\b|\.azure|\.kube|\.netrc|\.npmrc|\.pypirc|\.docker/config|Keychains|id_rsa|id_ed25519"
                     r"|(^|[/\s])\.env\b|Cookies|Login Data|\.config/gh|\.git-credentials)", re.I)
SYSTEM_DIRS = tuple(Path(p) for p in ("/usr", "/bin", "/sbin", "/opt/homebrew", "/opt/local", "/System", "/Library/Frameworks",
                                      "/Applications", "/dev", "/tmp", "/private/tmp", "/var/folders", "/private/var/folders"))
ACTING_SCRIPTS = re.compile(r"\b(osascript|sendmail|mailx?|msmtp|shortcuts\s+run)\b")
UPLOAD_COMMANDS = re.compile(r"\b(curl|wget|http|httpie|nc|ncat|scp|rsync|ftp)\b")
POSTING_FLAGS = re.compile(r"(\s-d\b|\s--data|\s-F\b|\s--form|\s-T\b|\s--upload-file|-X\s*(POST|PUT|PATCH|DELETE))", re.I)


def _decision(result: str, reason: str, **extra) -> dict:
    return {"result": result, "reason": reason, **extra}


def _action_name(tool: str) -> str:
    """The action part of an MCP tool name, e.g. mcp__abc__send_message -> send_message."""
    return tool.rsplit("__", 1)[-1].lower()


def classify_app_tool(tool: str) -> str:
    """read, draft, destructive or acting, from the verb in an MCP tool's name."""
    action = _action_name(tool)
    if any(action.startswith(v) for v in DESTRUCTIVE_VERBS):
        return "destructive"
    if action.startswith(("send", "reply", "forward", "post", "publish", "share")):
        return "acting"
    if any(action.startswith(v) for v in DRAFT_VERBS) or "draft" in action:
        return "draft"
    if any(action.startswith(v) for v in READ_VERBS):
        return "read"
    return "acting"  # anything not plainly a read or a draft waits for the person


def _paths_in(tool: str, arguments: dict) -> list[str]:
    keys = ("file_path", "path", "notebook_path") + (("pattern",) if tool == "Glob" else ())  # Grep's pattern is a regex, not a path
    return [str(arguments[k]) for k in keys if isinstance(arguments.get(k), str)]


def _shell_paths(command: str) -> list[str]:
    """Every word of a shell command that names a place: absolute, home-relative, or climbing out with '..'."""
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        words = command.split()
    found = []
    for word in words:
        for part in re.split(r"[=:]", word):
            if part.startswith(("/", "~")) or ".." in Path(part).parts:
                found.append(part)
    return found


def worker_guard(*, project_root: str, workspace: str = "", record_dir: str = "", readable: str = "") -> callable:
    """Factory for the native agents' guard; returns evaluate(event, config)."""
    root = Path(project_root).expanduser().resolve()
    record = Path(record_dir).expanduser().resolve() if record_dir else root / "record"
    archive = root / "archive"  # material from building the system, never needed by the worker
    inbox = record / "inbox"
    own_space = Path(workspace).expanduser().resolve() if workspace else root / "workspace"
    protected = [root / d for d in ("kit", "system", "agents", "scripts", "archive")] + [record]
    allowed = [Path(p).expanduser().resolve() for p in (readable or os.environ.get("PA_READABLE", "")).split(os.pathsep) if p.strip()]
    stores = [Path("~/.claude/projects").expanduser().resolve(), Path("~/.codex").expanduser().resolve()]
    private_roots = [inbox, *stores, *allowed]           # reading these marks the session as holding private data
    read_roots = [own_space, root / "kit", *private_roots]
    write_roots = [own_space, inbox]

    def place(path: str) -> Path | None:
        """Where a path really points; a relative one is taken from the agent's workspace, where it runs."""
        try:
            candidate = Path(path).expanduser()
            return (candidate if candidate.is_absolute() else own_space / candidate).resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    def inside(path: str, base: Path) -> bool:
        resolved = place(path)
        return resolved is not None and (resolved == base or base in resolved.parents)

    def within(path: str, roots: list[Path]) -> bool:
        return any(inside(path, r) for r in roots)

    def evaluate(event: dict, config: dict | None = None) -> dict:  # noqa: ARG001
        if event.get("type") != "tool_call":
            return ALLOW
        data = event.get("data") or {}
        tool = str(data.get("name") or event.get("target") or "")
        arguments = data.get("arguments") or {}
        tainted = bool((event.get("session_state") or {}).get(TAINT_KEY))

        # Omnigent's own relay tools are gated on their own path.
        if tool.startswith("mcp__omnigent__"):
            return ALLOW

        if tool.startswith(BROWSER_PREFIXES):
            return _decision("DENY", "The worker may not drive a browser: it could act as the person without any check. "
                                     "Use WebSearch or WebFetch for research, and the app connectors for the person's data.")

        if tool in WEB_TOOLS:
            if tainted:
                return _decision("DENY", "This session has read the person's private data, so it may not reach the web. "
                                         "Run the research in a fresh worker session.")
            return ALLOW

        if tool.startswith("mcp__"):
            kind = classify_app_tool(tool)
            if kind == "read":
                return {**ALLOW, "state_updates": [{"key": TAINT_KEY, "action": "set", "value": 1}]}
            if kind == "draft":
                return {**ALLOW, "state_updates": [{"key": TAINT_KEY, "action": "set", "value": 1}]}
            if kind == "destructive":
                return _decision("DENY", f"{_action_name(tool)} deletes something in the person's account; the worker never deletes.")
            return _decision("ASK", f"{_action_name(tool)} acts in the person's account. It needs the person's yes.")

        if tool in FILE_WRITE_TOOLS:
            paths = _paths_in(tool, arguments)
            if not paths or not all(within(p, write_roots) for p in paths):
                return _decision("DENY", f"A native agent may write only in its workspace ({own_space}) or the record's inbox ({inbox}).")
            return ALLOW

        if tool in FILE_READ_TOOLS:
            paths = _paths_in(tool, arguments) or ["."]  # no path means the workspace it runs in
            if any(SECRETS.search(p) for p in paths):
                return _decision("DENY", "Secret stores such as keys, tokens and passwords are never read.")
            if not all(within(p, read_roots) for p in paths):
                return _decision("DENY", f"A native agent may read only its workspace, the record's inbox, the person's Claude and Codex "
                                         f"conversation stores, and folders the person allowed. Not: {', '.join(paths)}")
            if any(within(p, private_roots) for p in paths):
                return {**ALLOW, "state_updates": [{"key": TAINT_KEY, "action": "set", "value": 1}]}
            return ALLOW

        if tool in SHELL_TOOLS:
            command = str(arguments.get("command") or "")
            if SECRETS.search(command):
                return _decision("DENY", "Secret stores such as keys, tokens and passwords are never read.")
            outside = [p for p in _shell_paths(command)
                       if not within(p, read_roots) and not any(inside(p, d) for d in SYSTEM_DIRS)]
            if outside:
                return _decision("DENY", f"A native agent works only in its workspace, the record's inbox and the folders it may read. "
                                         f"Not: {', '.join(outside[:3])}")
            if ACTING_SCRIPTS.search(command):
                return _decision("DENY", "Scripts that drive Mail, Messages or Shortcuts can act as the person; the worker may not run them.")
            if UPLOAD_COMMANDS.search(command):
                if tainted:
                    return _decision("DENY", "This session has read private data, so it may not make network requests from the shell.")
                if POSTING_FLAGS.search(command):
                    return _decision("DENY", "The worker may not send data out from the shell.")
            if any(str(p) in command for p in protected if p != archive) and re.search(r"(>|\btee\b|\bmv\b|\bcp\b|\brm\b|\bsed\s+-i)", command):
                writes_inbox_only = str(inbox) in command and not any(str(p) in command.replace(str(inbox), "") for p in protected if p != archive)
                if not writes_inbox_only:
                    return _decision("DENY", "The worker may not change the person's record or the system itself.")
            if PRIVATE_STORES.search(command) or any(within(p, private_roots) for p in _shell_paths(command)):
                return {**ALLOW, "state_updates": [{"key": TAINT_KEY, "action": "set", "value": 1}]}
            return ALLOW

        return ALLOW

    return evaluate


def person_approves(*, record_dir: str) -> callable:
    """Factory: every call that applies a proposal to the record raises an approval card.

    The agent can ask to apply a proposal, but only the person's click on the card
    lets it through, so approval stays the person's act, enforced by Omnigent."""
    record = Path(record_dir).expanduser().resolve()

    def evaluate(event: dict, config: dict | None = None) -> dict:  # noqa: ARG001
        if event.get("type") != "tool_call":
            return ALLOW
        data = event.get("data") or {}
        tool = str(data.get("name") or event.get("target") or "")
        if not tool.endswith("apply_proposal"):
            return ALLOW
        pid = str((data.get("arguments") or {}).get("proposal_id", ""))
        summary = f"Add to your record: proposal {pid}"
        path = record / "_proposals" / f"{pid}.yaml"
        if re.fullmatch(r"P-[0-9-]+", pid) and path.exists():
            import yaml
            p = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            summary = (f"Add to your record ({p.get('kind')} {p.get('name')}): {p.get('reason', '')}\n\n"
                       + str(p.get("content", ""))[:1500])
        return _decision("ASK", summary)

    return evaluate
