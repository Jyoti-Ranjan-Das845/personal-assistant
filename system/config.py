"""Paths and model choices, in one place.

Every location is worked out from where the pack sits, so it runs from any
folder on any machine. The person's record, the native agents' working folder
and the session state may live elsewhere: set PA_RECORD, PA_WORKSPACE or
PA_STATE. OMNIGENT_SERVER points at an Omnigent server other than the local one.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "kit"
CHARTERS = KIT / "charters"
TEMPLATE_RECORD = KIT / "templates" / "record"   # the empty record the pack ships with; a person's record starts as a copy


def _place(variable: str, default: Path) -> Path:
    return Path(os.environ.get(variable) or default).expanduser().resolve()


RECORD = _place("PA_RECORD", ROOT / "record")        # the person's record
WORKSPACE = _place("PA_WORKSPACE", ROOT / "workspace")  # where the native agents may work
STATE = _place("PA_STATE", ROOT / "state")           # traces and per-agent state
AGENTS = ROOT / "agents"                             # Omnigent configs, generated on this machine
READABLE = os.environ.get("PA_READABLE", "")         # extra folders the person lets the native agents read, joined by ":"
OMNIGENT_SERVER = os.environ.get("OMNIGENT_SERVER", "http://127.0.0.1:6767")

# Every model runs on the person's Claude subscription through the claude CLI.
MODELS = {
    "chief_of_staff": "claude-opus-5-5",
    "interviewer": "claude-opus-5-5",
    "curator": "claude-opus-5-5",       # judges conflicts and drift across the whole record
    "builder": "claude-sonnet-5-5",
    "analyst": "claude-opus-5-5",       # every later reading rests on its timeline and table
    "tester": "claude-opus-5-5",        # fills the competing-hypotheses matrix the code weighs
    "advisor": "claude-opus-5-5",
    "challenger": "claude-fable-5-1",   # a different model from the advisor, on purpose
    "preparer": "claude-opus-5-5",
    "case_finder": "claude-opus-5-5",   # native: reads strangers' text, so the strongest model
    "policy_checker": "claude-sonnet-5-5",   # a safety check: precision matters more than cost
    "quarantine_reader": "claude-haiku-5-5",
}

# The agents the person talks to directly. The others are run by code.
FRONT_DOOR = ("chief_of_staff", "interviewer", "curator")
