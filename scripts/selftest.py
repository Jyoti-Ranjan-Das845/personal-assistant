"""Check the system's code paths without calling any model.

    python3 scripts/selftest.py

It works on a temporary copy of the empty record and on a small made-up record it
writes itself, so nothing real is touched. A model call anywhere here is a bug in the test.
"""

import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from system import decide, interview, policy, proposals  # noqa: E402
from system.config import TEMPLATE_RECORD  # noqa: E402
from system.record import Record  # noqa: E402

FAILED = []

ENTRY = """---
id: J-20200301-old-job
date: 2020-03-01
area: career
kind: choice
options: [Stay, Take the new job]
choice: Take the new job
review_on: 2020-09-01
---

## Situation

A new job paid more, under a manager from head office.

## Their reasons (their own words, told later)

"It paid more."

## What they noticed

Not asked yet.

## Outcome (added on the review date)

Took it.

## Hindsight note (labelled as hindsight)

## Grade
"""


def fixture(root: Path) -> Path:
    """A small made-up record: one person, one decision, one fact, so the checks rely on no real one."""
    shutil.copytree(TEMPLATE_RECORD, root)
    (root / "person.yaml").write_text("name: Sam Example\npronouns: they/them\n", encoding="utf-8")
    (root / "journal" / "J-20200301-old-job.md").write_text(ENTRY, encoding="utf-8")
    (root / "facts" / "cash-reserve.yaml").write_text("key: cash-reserve\nvalue: 200000\nas_of: 2019-06-01\nreview_by: 2020-06-01\n", encoding="utf-8")
    return root


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
    if not ok:
        FAILED.append(name)


def refused(fn) -> bool:
    try:
        fn()
    except (ValueError, PermissionError):
        return True
    return False


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    empty = tmp / "empty"
    shutil.copytree(TEMPLATE_RECORD, empty)
    mock = fixture(tmp / "made-up")
    rec = Record(empty, date(2026, 11, 10))

    # proposals: what the record will and will not take
    check("threshold needs their words choosing one amount",
          refused(lambda: proposals.propose(rec, "interviewer", "threshold", "TH-01", "id: TH-01\namount: 50000\n", "r")))
    proposals.propose(rec, "interviewer", "threshold", "TH-01",
                      "id: TH-01\nrule: More than 50000 is high stakes\namount: 50000\ntheir_words_choosing_it: Fifty. Above that I lose sleep.\n", "r")
    check("hard line needs their words",
          refused(lambda: proposals.propose(rec, "interviewer", "hard_line", "HL-01", "id: HL-01\nrule: Never sell the flat\n", "r")))
    check("reminder needs a date and what to say",
          refused(lambda: proposals.propose(rec, "chief_of_staff", "reminder", "fees", "what: pay fees\n", "r")))
    check("a safeguard waiver never becomes a precedent",
          refused(lambda: proposals.propose(rec, "chief_of_staff", "precedent", "x", "ruling: just put it in, don't ask me again\n", "r")))

    (mock / "facts").mkdir(exist_ok=True)
    rmock = Record(mock, date(2026, 11, 10))
    key = next(e["data"]["key"] for e in rmock.yaml_entries("facts"))
    old = next(e["data"] for e in rmock.yaml_entries("facts") if e["data"]["key"] == key)
    check("a figure confirmed unchanged keeps its date",
          refused(lambda: proposals.propose(rmock, "chief_of_staff", "fact", key, f"key: {key}\nvalue: {old['value']!r}\nas_of: 2026-11-10\n", "r", op="replace")))

    # journal additions keep their label and fill empty sections
    entry = (mock / "journal" / "J-20200301-old-job.md").read_text(encoding="utf-8")
    out = proposals.append_to_entry(entry, "## Addition, 2026-11-18 (told after the outcome)\n\n## What they noticed\n\nHe had never done a night.\n\n## Decision now\n\nStays.", "2026-11-18")
    check("addition keeps its 'told after the outcome' label", "told after the outcome" in out, out[-300:])
    check("addition fills the empty noticed section", "He had never done a night.\n\n(Added on 2026-11-18, told after the outcome.)" in out)
    check("addition adds no duplicate heading", out.count("## What they noticed") == 1 and out.count("## Added on") == 1)

    # the interviewer's next step
    rec2 = Record(tmp / "fresh", date(2026, 11, 10))
    shutil.copytree(TEMPLATE_RECORD, rec2.root)
    check("empty record starts with name", "name" in interview.next_step(rec2))
    proposals.propose(rec2, "interviewer", "identity", "person", "name: A\npronouns: she/her\n", "r")
    check("then hard lines", "hard lines" in interview.next_step(rec2), interview.next_step(rec2))
    proposals.propose(rec2, "interviewer", "hard_line", "HL-01", "id: HL-01\nrule: Never touch the tin\nwhy: The tin stays.\n", "r")
    check("one hard line is not the end: it asks for any other", "any other" in interview.next_step(rec2, {}), interview.next_step(rec2, {}))
    check("confirmed hard lines move on", "hard lines" not in interview.next_step(rec2, {"hard_limits": {"status": "confirmed"}}))
    proposals.propose(rec2, "interviewer", "journal", "J-2016-private-job", "## Situation\n\nTook a private job.\n\n## What they noticed\n\nNot asked yet.\n", "r")
    check("a decision told without cues is walked through next", interview.next_step(rec2).startswith("Walk through J-2016-private-job"))
    proposals.propose(rec2, "interviewer", "journal", "J-2016-private-job", "## What they noticed\n\nThe room was cold.\n", "r", op="append")
    check("cues mark it walked through", not interview.next_step(rec2).startswith("Walk through"), interview.next_step(rec2))
    state = proposals.interview_state(rec2)
    state["time_short"] = True
    proposals.save_interview_state(rec2, state)
    nxt = interview.next_step(rec2)
    check("short time asks for the missing essentials", nxt.startswith("Time is short") and "hard lines" in nxt and "topics" in nxt, nxt)

    # record: skills, reminders, trackers
    (empty / "skills" / "career").mkdir(parents=True)
    (empty / "skills" / "career" / "SKILL.md").write_text("---\nname: career\ndescription: Use for job offers.\n---\n\n# Skill: career\n", encoding="utf-8")
    (empty / "reminders" / "fees.yaml").write_text("date: 2026-11-14\nwhat: Pay the fees\n", encoding="utf-8")
    check("skills are listed, templates are not", [s["name"] for s in rec.skills()] == ["career"], str(rec.skills()))
    check("skills reach the decision procedure", "# Skill: career" in rec.dump())
    check("a reminder due this week is found", [r["what"] for r in rec.reminders_due()] == ["Pay the fees"])

    # policy: money in the question only, never ids or dates
    check("ids and dates are not money", policy.amounts_in("like J-20250610 on 2026-11-07, ₹49,500") == [49500.0])
    check("any currency counts, at any size", policy.amounts_in("a $250 fee, €1.2m, 3 lakh rupees, 400 dollars, aged 34, 20 percent")
          == [250.0, 1200000.0, 300000.0, 400.0], str(policy.amounts_in("a $250 fee, €1.2m, 3 lakh rupees, 400 dollars, aged 34, 20 percent")))

    # weighing the matrix
    cells = lambda *v: [{"id": f"J{i}", "verdict": x, "feature_present": True} for i, x in enumerate(v)]  # noqa: E731
    rules = [
        {"rule": "when the post is permanent, they stay", "source": "advisor", "cases": cells("fits", "fits"), "today": {"predicts": "Stay", "applies": "directly"}},
        {"rule": "when the boss has fewer years in the work, they leave", "source": "challenger", "cases": cells("fits", "fits"), "today": {"predicts": "Take it", "applies": "directly"}},
        {"rule": "when the boss is younger, they leave", "source": "the person", "cases": cells("fits", "unexplained"), "today": {"predicts": "Stay", "applies": "directly"}},
    ]
    ranked = decide.weigh(rules, ["Take it", "Stay"])
    best = ranked[0]
    rivals = [r for r in ranked[1:] if r["predicts"] != best["predicts"] and decide.as_well_supported(r, best)]
    level, why = decide.confidence_from(best, bool(rivals), [{"choice": "Stay"}, {"choice": "Take it"}], best["predicts"])
    check("two equally supported rules make it contested and low", bool(rivals) and level == "low", f"{level} {why}")
    rep = decide.report(best["predicts"], best, rivals, ranked, {"choice": "Stay", "rule": rules[0]["rule"]}, level, why,
                        "predict", {"money_threshold": 50000, "largest_amount_mentioned": None}, "", "", ["Take it", "Stay"])
    lines = decide.say_in_order(rep, "predict")
    check("contested reads say so first", rep["contested"] and lines[0].startswith("Two readings"), lines[0])
    check("a stated reason that fails a case is reported", any("does not bear out" in l for l in lines), json.dumps(lines))
    rep2 = dict(rep, contested=False, stale_facts=["cash-reserve = 2 lakh (as of 2019-06-01)"], options_missing_from_the_list="a provident-fund advance",
                should_not_matter="The first number they heard (J-2019)")
    lines2 = decide.say_in_order(rep2, "predict")
    check("stale facts come first, and missing options and anchors are said",
          lines2[0].startswith("Facts this rests on") and any("provident-fund" in l for l in lines2) and any("sway" in l for l in lines2))
    check("features are read from the brief", decide.features('x\n```json\n{"features": ["a", "b"]}\n```') == ["a", "b"])

    # the native agents' guard: their own folders only
    from system.omnigent_policies import worker_guard
    space = ROOT / "workspace"  # the guard only judges paths here; nothing is written
    guard = worker_guard(project_root=str(ROOT), workspace=str(space), record_dir=str(mock))
    def verdict(name, args, tainted=False):
        return guard({"type": "tool_call", "data": {"name": name, "arguments": args},
                      "session_state": {"pa_worker_read_private": 1} if tainted else {}}, {})
    home = Path("~").expanduser()
    check("it may read and write in its workspace",
          verdict("Read", {"file_path": str(space / "a.md")})["result"] == "ALLOW" and verdict("Write", {"file_path": "notes.md", "content": "x"})["result"] == "ALLOW")
    check("it may write findings to the inbox", verdict("Write", {"file_path": str(mock / "inbox" / "f.md"), "content": "x"})["result"] == "ALLOW")
    check("it may not read elsewhere on the machine", verdict("Read", {"file_path": str(home / "Documents" / "x.md")})["result"] == "DENY")
    check("it never reads secret stores", verdict("Read", {"file_path": str(home / ".ssh" / "id_rsa")})["result"] == "DENY")
    stores = verdict("Read", {"file_path": str(home / ".codex" / "sessions" / "a.jsonl")})
    check("it may read their conversation stores, which marks the session", stores["result"] == "ALLOW" and bool(stores.get("state_updates")))
    check("it may not write the system or the record", verdict("Write", {"file_path": str(ROOT / "kit" / "x.md"), "content": "x"})["result"] == "DENY"
          and verdict("Write", {"file_path": str(mock / "core_profile.md"), "content": "x"})["result"] == "DENY")
    check("shell is held to the same folders", verdict("Bash", {"command": f"cat {home}/Documents/notes.md"})["result"] == "DENY"
          and verdict("Bash", {"command": "cat ../system/decide.py"})["result"] == "DENY"
          and verdict("Bash", {"command": "ls -la && python3 summarise.py notes.md"})["result"] == "ALLOW")
    check("after private data, no web", verdict("WebSearch", {"query": "x"}, tainted=True)["result"] == "DENY"
          and verdict("WebSearch", {"query": "x"})["result"] == "ALLOW")
    check("deleting in an app is denied, sending asks", verdict("mcp__mail__trash_message", {})["result"] == "DENY"
          and verdict("mcp__mail__send_message", {})["result"] == "ASK")

    # someone else's decision is never predicted
    calls = []
    decide.ask = lambda prompt, **k: calls.append(prompt) or "## What lands on the person\n\nThey work nights.\n\n## Not covered\n\nThe shop's income."
    decide.ask_json = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no reading for someone else's decision"))
    decide.policy.check_options = lambda *a, **k: {}
    result = decide.run(Record(mock, date(2026, 11, 10)), "Their partner's job offer", ["Take it", "Keep the shop"], whose="Alex")
    check("someone else's decision runs only the analyst", len(calls) == 1 and result["mode"] == "someone else's decision")
    check("and says it is their decision first", "Alex's decision" in result["report"]["say_in_order"][0])

    shutil.rmtree(tmp)
    print(f"\n{'All checks passed.' if not FAILED else f'{len(FAILED)} failed: ' + ', '.join(FAILED)}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
