"""Assemble each agent's instructions from prompts/ and the person's record."""

from personal_assistant.config import CHARTERS, FRONT_DOOR, PROMPTS
from personal_assistant.record import Record


def header(record: Record, with_date: bool = True) -> str:
    person = record.person()
    name, pronouns = person.get("name"), person.get("pronouns")
    who = (f"You serve {name} ({pronouns}). Wherever these instructions say \"the person\", they mean {name}."
           if name else "You serve one person whose record is still being built; their name is not on record yet.")
    when = (f"Today is {record.today.isoformat()}. Use this date in everything you write and count from it, even if your "
            "environment shows another date." if with_date else "Use today's date from the today tool.")
    return f"{who} {when}"


def charter(role: str) -> str:
    return (CHARTERS / f"{role}.md").read_text(encoding="utf-8").strip()


def constitution() -> str:
    return (PROMPTS / "constitution.md").read_text(encoding="utf-8").strip()


NATIVE = ("worker", "case_finder")
NATIVE_PROMPT_LIMIT = 12000  # bytes: Omnigent passes a native agent's prompt inside one tmux command, capped near 16 KB


def build(role: str, record: Record, with_date: bool = True) -> str:
    """Instructions for one agent. Front-door agents also carry the approved core profile. A native agent, which has
    its own file access, reads the constitution from disk, because its whole prompt must fit in one tmux command."""
    rules = ("---\n\nEvery agent in this system follows its constitution. Read it before you start, with your file tools: "
             f"{PROMPTS / 'constitution.md'}" if role in NATIVE else "---\n\n" + constitution())
    parts = [header(record, with_date), charter(role), rules]
    if role in FRONT_DOOR or role in ("worker", "case_finder", "preparer"):
        parts.insert(1, f"Workers file their findings in {record.root / 'inbox'}.")
    if role in FRONT_DOOR:
        parts.append("---\n\n# Their record: core profile (approved)\n\n" + record.profile().strip())
        skills = record.skills()
        if skills:  # the approved skills, so the agent can open the one an area needs
            parts.append("# Their skills\n\nWhen a request falls in one of these areas, read that skill with read_record before you answer.\n\n"
                         + "\n".join(f"- {s['name']}: {s['description']} ({s['file']})" for s in skills))
    return "\n\n".join(parts)
