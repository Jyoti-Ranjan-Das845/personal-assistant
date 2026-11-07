"""What the interviewer should do next, worked out in code.

An interviewer that decides its own next question drifts: under time pressure
it keeps the checklist and drops the stories, which are the only material
that shows how the person decides. So the order lives here. It is read from
the record itself (what is approved or waiting for approval) and from the
interview's own state (which past decisions came up, which were walked
through, whether time is short), and the interviewer is told the next step
every time it updates the ledger.
"""

from system import proposals
from system.record import Record

ESSENTIALS = [
    ("name", "their name and pronouns"),
    ("hard_lines", "their hard lines, each in their own words, asking of anything they say they cannot or will not do whether it is a "
                   "line they would never cross, and then, once, whether there is any other; when they say there is none, set "
                   "hard_limits to confirmed in the ledger"),
    ("threshold", "the amount of money above which a decision is high stakes for them, settled on one number in their own words"),
    ("answers", "how they want answers"),
    ("topics", "the topics they do not want you to guess about"),
    ("who", "who they are now: work, family, situation and what they are working towards this season"),
]
WHEN_TIME_IS_SHORT = ("hard_lines", "threshold", "answers", "topics")
SECTIONS = {"answers": ("How", "answers"), "topics": ("Topics not to guess about", "topics_not_to_guess"), "who": ("Who", "who")}
WALK_THROUGH = (
    "Walk through {name} now, before anything else, one short question per message: ask them to tell it from the start, "
    "then go back to particular moments and ask what they saw, heard, were told or expected then, not why. Propose each "
    "detail in their words under the entry's 'What they noticed' heading; that marks it walked through. Ask for the "
    "reason they would give anyone only after the walk-through."
)


def have(record: Record, pending: list[dict], key: str, ledger: dict | None = None) -> bool:
    kinds = {(p["kind"], p["name"]) for p in pending}
    if key == "name":
        return bool(record.person().get("name")) or any(k == "identity" for k, _ in kinds)
    if key == "hard_lines":  # done only once they have been asked whether there are any others
        some = bool(record.rules()["hard_lines"]) or any(k == "hard_line" for k, _ in kinds)
        return some and ((ledger or {}).get("hard_limits") or {}).get("status") == "confirmed"
    if key == "threshold":
        return bool(record.rules()["thresholds"]) or any(k == "threshold" for k, _ in kinds)
    heading, name = SECTIONS[key]
    return record.section_filled(heading) or ("profile_section", name) in kinds


def next_step(record: Record, ledger: dict | None = None) -> str:
    state = proposals.interview_state(record)
    pending = proposals.pending(record)
    missing = [(key, what) for key, what in ESSENTIALS if not have(record, pending, key, ledger)]
    stories = state.get("decisions") or {}
    open_stories = [name for name, entry in stories.items() if entry.get("status") == "offered"]
    walked = [name for name, entry in stories.items() if entry.get("status") == "walked"]

    if state.get("time_short"):
        short = [what for key, what in missing if key in WHEN_TIME_IS_SHORT]
        if short:
            return "Time is short. Ask now for " + "; then ".join(short) + ". Then close."
        return ("Time is short and the essentials are in. Close now: tell them in a few lines what is in their record, "
                "what is waiting for their approval and what is left for next time, and write the same in your working notes.")
    if open_stories:
        return WALK_THROUGH.format(name=open_stories[0])
    if missing:
        return f"Next: {missing[0][1]}."
    if len(walked) < 5:
        return (f"Next: another real past decision ({len(walked)} walked through so far; aim for five to eight across "
                "different areas of their life). Ask them to name one, then walk through it.")
    for dimension, entry in (ledger or {}).items():
        if isinstance(entry, dict) and entry.get("status") != "confirmed" and entry.get("next"):
            return f"Next, from the guide, for {dimension}: {entry['next'][0]}"
    return "The essentials and enough decisions are in. Ask whether they want to go on, and otherwise close properly."
