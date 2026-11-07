"""Proposals: the only way an agent can ask for the record to change.

An agent proposes; the file lands in record/_proposals/ as pending. Only
the person's approval (a card they click in the chat, or `pa approve`) applies it and commits it to git. The
target path is worked out here from the kind and name, never taken from the
agent, so no proposal can reach outside the record or into the system itself.
"""

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from personal_assistant.policy import check_proposal
from personal_assistant.redact import redact

# Phrases that would turn a refused request into a standing rule that weakens a safeguard.
WAIVERS = re.compile(
    r"(?i)(don'?t|do not|never) (ask|check with) (me|her|him|them)( again)?|without (asking|approval|checking)"
    r"|skip (the )?approvals?|approve (it|them|everything|all)( automatically)?( for me)?"
    r"|(treat|take) .{0,40} as (if )?(they were |it were |coming )?from (me|her|him|them)|act (on|in) my name"
    r"|no need to (ask|check|confirm)|just (put|add) it in")
from personal_assistant.record import Record

SECTIONS = {
    "who": "## Who",
    "values": "## Values",
    "tie_breakers": "## Tie-breakers",
    "blind_spots": "## Blind spots",
    "answers": "## How",
    "topics_not_to_guess": "## Topics not to guess about",
}

KINDS = {
    "journal": "journal/{name}.md",
    "fact": "facts/{name}.yaml",
    "person": "people/{name}.yaml",
    "precedent": "precedents/{name}.yaml",
    "note": "notes/{name}.md",
    "skill": "skills/{name}/SKILL.md",
    "tracker": "trackers/{name}.md",
    "reminder": "reminders/{name}.yaml",
    "identity": "person.yaml",
    "profile_section": "core_profile.md",
    "hard_line": "core_profile.md",
    "threshold": "core_profile.md",
}

# What each agent may propose. The builder cannot touch the profile or journal.
ALLOWED = {
    "chief_of_staff": set(KINDS),
    "interviewer": set(KINDS) - {"skill", "tracker"},
    "curator": set(KINDS),
    "builder": {"skill", "tracker", "precedent", "hard_line", "note", "reminder"},
    "preparer": set(),
}


def slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")
    if not cleaned:
        raise ValueError("a proposal needs a name")
    return cleaned[:80]


def propose(record: Record, role: str, kind: str, name: str, content: str, reason: str, op: str = "add") -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; use one of {sorted(KINDS)}")
    if kind not in ALLOWED.get(role, set()):
        raise PermissionError(f"the {role} may not propose a {kind}")
    if kind == "journal" and op == "replace":
        raise ValueError("journal entries are append-only: use op 'append' to add a dated addition; earlier text is never rewritten")
    if op == "append" and kind != "journal":
        raise ValueError("only journal entries take op 'append'; use 'replace' for other kinds")
    if op == "append" and not content.strip():
        raise ValueError("an addition needs content")
    if op == "append" and not record.resolve(KINDS[kind].format(name=slug(name))).exists():
        waiting = next((p for p in pending(record) if p["kind"] == "journal" and p["name"] == slug(name)), None)
        if not waiting:
            raise ValueError(f"no journal entry {name!r} to append to; list the journal to find its file name")
        # the entry is still waiting for approval: add to it, so the person approves one complete entry
        waiting["content"] = append_to_entry(waiting["content"], redact(content), record.today.isoformat()).strip()
        waiting["reason"] = f"{waiting['reason']} Added to before approval: {reason}"
        (record.root / "_proposals" / f"{waiting['id']}.yaml").write_text(
            yaml.safe_dump(waiting, sort_keys=False, allow_unicode=True), encoding="utf-8")
        note_decision(record, waiting["name"], waiting["content"])
        return waiting
    if kind == "profile_section" and name not in SECTIONS:
        raise ValueError(f"profile_section name must be one of {sorted(SECTIONS)}")
    if kind != "journal" and WAIVERS.search(content):
        raise PermissionError("this would record a request to weaken a safeguard (approval, checks, or who speaks for the person); "
                              "such requests are refused and never become rules or precedents. Record at most a journal note that they asked.")
    content = redact(content)
    if kind == "fact" and op != "remove":
        target = record.resolve(KINDS[kind].format(name=slug(name)))
        old = (yaml.safe_load(target.read_text(encoding="utf-8")) or {}) if target.exists() else {}
        new = yaml.safe_load(content) or {}
        if old and new.get("value") == old.get("value") and str(new.get("as_of", old.get("as_of"))) != str(old.get("as_of")):
            raise ValueError("the value is unchanged, so its as_of date stays: only a new count, statement or document gives a fact "
                             "a new date. If they said it is the same, add confirmed_unchanged_on with today's date instead.")
    if kind in ("fact", "person", "precedent", "hard_line", "threshold", "identity", "reminder"):
        parsed = yaml.safe_load(content)  # must parse; raises with a clear message if not
        parsed = parsed[0] if isinstance(parsed, list) and parsed else parsed
        if kind == "threshold" and op != "remove":
            missing = [f for f in ("amount", "their_words_choosing_it") if not (parsed or {}).get(f)]
            if missing:
                raise ValueError("a threshold needs one amount and the person's own words choosing it (their_words_choosing_it). "
                                 "If they gave a range or several amounts, ask them once to settle on one number, then propose it.")
        if kind == "hard_line" and op != "remove" and not (parsed or {}).get("why"):
            raise ValueError("a hard line needs their own words in 'why'; what they said when they stated the line is usually enough")
        if kind == "reminder" and not ((parsed or {}).get("date") and (parsed or {}).get("what")):
            raise ValueError("a reminder needs 'date' (the day to remind them) and 'what' (what to tell them)")
    folder = record.root / "_proposals"
    folder.mkdir(exist_ok=True)
    pid = f"P-{record.today.strftime('%Y%m%d')}-{datetime.now().strftime('%H%M%S%f')}"
    proposal = {
        "id": pid,
        "status": "pending",
        "proposed_by": role,
        "kind": kind,
        "name": slug(name) if kind not in ("profile_section", "identity", "hard_line", "threshold") else name,
        "op": op,
        "reason": reason,
        "content": content,
        **check_proposal(kind),
    }
    (folder / f"{pid}.yaml").write_text(yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if kind == "journal":
        note_decision(record, slug(name), content)
    return proposal


# --- the interview's own state: which past decisions came up and which were walked through ---------

PLACEHOLDER = re.compile(r"(?i)^\s*(not (yet )?(asked|recorded|given)( yet)?\.?)?\s*$")


def noticed(content: str) -> bool:
    """Whether an entry's 'What ... noticed' section holds real cues rather than a placeholder."""
    match = re.search(r"## What \w+ noticed[^\n]*\n(.*?)(?=\n## |\Z)", content, re.S)
    body = (match.group(1) if match else "").strip()
    body = re.sub(r"(?i)the cues they picked up on.*", "", body).strip()
    return bool(body) and not PLACEHOLDER.match(body)


def interview_state(record: Record) -> dict:
    path = record.root / "_working" / "interview_state.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None) or {"decisions": {}, "time_short": False}


def save_interview_state(record: Record, state: dict) -> None:
    folder = record.root / "_working"
    folder.mkdir(exist_ok=True)
    (folder / "interview_state.yaml").write_text(yaml.safe_dump(state, sort_keys=False, allow_unicode=True), encoding="utf-8")


def note_decision(record: Record, name: str, content: str = "", walked: bool = False) -> None:
    state = interview_state(record)
    entry = state["decisions"].setdefault(name, {"status": "offered", "since": record.today.isoformat()})
    if walked or noticed(content):
        entry["status"] = "walked"
    save_interview_state(record, state)


def pending(record: Record) -> list[dict]:
    folder = record.root / "_proposals"
    if not folder.is_dir():
        return []
    items = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("P-*.yaml"))]
    return [p for p in items if p["status"] == "pending"]


def all_proposals(record: Record) -> list[dict]:
    folder = record.root / "_proposals"
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("P-*.yaml"))] if folder.is_dir() else []


# --- applying, only on the person's approval ---------------------------------

def _replace_section(profile: str, heading_prefix: str, content: str) -> str:
    lines = profile.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(heading_prefix)), None)
    if start is None:
        raise ValueError(f"no section starting {heading_prefix!r}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = content.strip().splitlines()
    if body and body[0].startswith("## "):
        body = body[1:]
    return "\n".join(lines[: start + 1] + [""] + body + [""] + lines[end:]) + "\n"


def _edit_rules(profile: str, kind: str, op: str, content: str) -> str:
    match = re.search(r"(## Machine-readable rules.*?```yaml\n)(.*?)(```)", profile, re.S)
    rules = yaml.safe_load(match.group(2)) or {}
    key = "hard_lines" if kind == "hard_line" else "thresholds"
    items = rules.get(key) or []
    entry = yaml.safe_load(content)
    entry = entry[0] if isinstance(entry, list) else entry
    items = [i for i in items if i.get("id") != entry.get("id")]
    if op != "remove":
        items.append(entry)
    rules[key] = items
    rules.setdefault("hard_lines", rules.get("hard_lines") or [])
    rules.setdefault("thresholds", rules.get("thresholds") or [])
    block = yaml.safe_dump({"hard_lines": rules["hard_lines"], "thresholds": rules["thresholds"]}, sort_keys=False, allow_unicode=True)
    return profile[: match.start(2)] + block + profile[match.end(2):]


def apply(record: Record, proposal: dict) -> Path:
    kind, name, content = proposal["kind"], proposal["name"], proposal["content"]
    target = record.resolve(KINDS[kind].format(name=name))
    if kind in ("profile_section", "hard_line", "threshold"):
        profile = record.profile()
        if kind == "profile_section":
            profile = _replace_section(profile, SECTIONS[name], content)
        else:
            profile = _edit_rules(profile, kind, proposal.get("op", "add"), content)
        profile = re.sub(r"\nTEMPLATE:[^\n]*\n", "\n", profile)
        target.write_text(profile, encoding="utf-8")
    elif proposal.get("op") == "remove":
        target.unlink(missing_ok=True)
    elif proposal.get("op") == "append":  # the journal is append-only, like a lab notebook
        target.write_text(append_to_entry(target.read_text(encoding="utf-8"), content, record.today.isoformat()), encoding="utf-8")
    elif kind in ("fact", "person") and target.exists():  # an update keeps the fields it does not mention
        old = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        new = yaml.safe_load(content) or {}
        target.write_text(yaml.safe_dump({**old, **new}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip() + "\n", encoding="utf-8")
    return target


# --- journal additions -----------------------------------------------------

EMPTY = re.compile(r"(?i)^\s*(not (yet )?(asked|recorded|given)( yet)?\.?|—|-|tbd|none yet\.?)?\s*$")
OWN_HEADING = re.compile(r"(?i)^#+\s*(added|addition|update|appended)\b[^\n]*\n?")
OWN_HEADING_WORDS = re.compile(r"(?i)^#+\s*(added|addition|update|appended)( on)?[\s,:-]*(\d{4}-\d{2}-\d{2})?[\s,:-]*")


def _key(heading: str) -> str:
    return " ".join(re.sub(r"\(.*?\)", "", heading.lstrip("#")).lower().split()).strip(" .:,")


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) pairs; the text before the first heading has an empty heading."""
    parts, heading, body = [], "", []
    for line in text.splitlines():
        if line.startswith("## "):
            parts.append((heading, "\n".join(body)))
            heading, body = line, []
        else:
            body.append(line)
    parts.append((heading, "\n".join(body)))
    return parts


def append_to_entry(entry: str, content: str, today: str) -> str:
    """Add to a journal entry without rewriting it. A section of the addition whose heading matches a section of
    the entry that is still empty (an Outcome or Hindsight note not yet written) fills that section, marked with
    the date; everything else goes under one dated heading at the end. Text already written is never changed."""
    content = content.strip()
    label = ""  # the agent's own heading may carry a label, such as "told after the outcome", that must survive
    first = OWN_HEADING.match(content)
    if first:
        label = OWN_HEADING_WORDS.sub("", first.group(0).strip()).strip(" ()")
        content = content[first.end():].strip()
    entry_parts = _sections(entry.rstrip())
    leftover = []
    for heading, body in _sections(content):
        key = _key(heading)
        slot = next((i for i, (h, b) in enumerate(entry_parts) if key and h and EMPTY.match(b)
                     and (_key(h).startswith(key) or key.startswith(_key(h)))), None)
        if slot is not None and body.strip():
            entry_parts[slot] = (entry_parts[slot][0], f"\n{body.strip()}\n\n(Added on {today}{', ' + label if label else ''}.)\n")
        elif heading or body.strip():
            leftover.append((("#" + heading) if heading else "", body.strip()))
    text = "\n".join(f"{h}\n{b}" if h else b for h, b in entry_parts).rstrip()
    rest = "\n\n".join(f"{h}\n\n{b}".strip() for h, b in leftover if h or b).strip()
    if rest:
        text += f"\n\n## Added on {today}{' (' + label + ')' if label else ''}\n\n{rest}"
    return text + "\n"


def commit(record: Record, message: str) -> None:
    if (record.root / ".git").is_dir():
        subprocess.run(["git", "add", "-A"], cwd=record.root, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=record.root, capture_output=True)


def resolve(record: Record, ids: list[str], approve: bool, by: str = "the person") -> list[str]:
    """Approve or reject pending proposals. Only the person's own command calls this."""
    done, changed = [], set()
    folder = record.root / "_proposals"
    for proposal in pending(record):
        if "all" not in ids and proposal["id"] not in ids:
            continue
        proposal["status"] = "approved" if approve else "rejected"
        proposal["resolved_by"] = by
        if approve:
            apply(record, proposal)
            changed.add(proposal["kind"])
        (folder / f"{proposal['id']}.yaml").write_text(yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True), encoding="utf-8")
        done.append(proposal["id"])
    if done:
        commit(record, f"{'Approved' if approve else 'Rejected'} {', '.join(done)}")
    if approve and changed & REFRESH and record.root == LIVE_RECORD:
        refresh_agents()
    return done


# Approved changes that alter what the agents' instructions carry: their name, profile, rules and skills.
REFRESH = {"identity", "profile_section", "hard_line", "threshold", "skill"}
from personal_assistant.config import RECORD as LIVE_RECORD  # noqa: E402  the record the live agents use


def refresh_agents() -> None:
    """Rebuild the Omnigent agent configs so new sessions start from the approved record."""
    script = Path(__file__).resolve().parent / "build_agents.py"
    subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=script.parent.parent)
