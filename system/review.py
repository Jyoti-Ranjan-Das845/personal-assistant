"""Checks the weekly review runs in code, so the curator starts from what the
whole record shows rather than from what it happened to open.

- Rulings whose wording reaches past a hard line.
- Pairs of rulings that cannot both be followed, and pairs that only look alike.
- For each item due, the entries that bear on it, in full.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor

import yaml

from system.config import CHARTERS, MODELS
from system.llm import ask_json
from system.record import Record

CHECKER = (CHARTERS / "precedent_checker.md").read_text(encoding="utf-8")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip(" .,'\"")


def precedents(record: Record) -> list[dict]:
    return [{"id": e["data"].get("id", e["path"].stem), **e["data"]} for e in record.yaml_entries("precedents")]


def rulings_against_hard_lines(record: Record) -> list[dict]:
    """A ruling must never open a way round a hard line, even by being worded too widely."""
    pairs = [(p, line) for p in precedents(record) if p.get("ruling") for line in record.rules()["hard_lines"]]

    def check(pair):
        prec, line = pair
        question = (f"Question: a ruling against a hard line.\nHard line: {line['rule']}\n"
                    f"Ruling {prec['id']}: {prec['ruling']}\nApplies when: {prec.get('applies_when', '')}")
        return ask_json(question, system=CHECKER, model=MODELS["policy_checker"], timeout=300)

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(check, pairs))
    found = []
    for (prec, line), answer in zip(pairs, answers):
        words = str(answer.get("words", ""))
        if answer.get("leaves_room") and words and _norm(words) in _norm(prec["ruling"]):  # the words must really be there
            found.append({"precedent": prec["id"], "ruling": prec["ruling"], "hard_line": line.get("id"),
                          "line": line["rule"], "words": words, "how": answer.get("how", "")})
    return found


def rulings_that_conflict(record: Record) -> dict:
    items = precedents(record)
    if len(items) < 2:
        return {"conflicts": [], "look_alike_but_do_not_conflict": []}
    text = yaml.safe_dump(items, sort_keys=False, allow_unicode=True)
    answer = ask_json(f"Question: rulings that pull apart.\nToday: {record.today}\n\n{text}",
                      system=CHECKER, model=MODELS["curator"], timeout=600)
    ids = {p["id"] for p in items}
    dated = {p["id"]: str(p.get("date", "")) for p in items}
    keep = lambda pair: pair.get("a") in ids and pair.get("b") in ids  # noqa: E731
    conflicts = [{**c, "newer": max((c["a"], c["b"]), key=lambda i: dated[i])} for c in answer.get("conflicts") or [] if keep(c)]
    return {"conflicts": conflicts,
            "look_alike_but_do_not_conflict": [c for c in answer.get("look_alike_but_do_not_conflict") or [] if keep(c)]}


def profile_against_record(record: Record) -> dict:
    """Statements in the profile that the dated record has overtaken (an age, a figure, a situation), and recent
    choices that run against a value, tie-breaker or blind spot in it. Each must quote both sides, and the quotes
    are checked in code, so nothing is raised on a guess."""
    journal = record.journal()
    recent = sorted(journal, key=lambda e: str(e["front"].get("date", "")))[-12:]
    facts = yaml.safe_dump([e["data"] for e in record.yaml_entries("facts")], sort_keys=False, allow_unicode=True)
    text = "\n\n".join(e["text"] for e in recent)
    answer = ask_json(f"Question: the profile against the record.\nToday: {record.today}\n\n# Profile\n{record.profile()}\n\n"
                      f"# Facts\n{facts}\n\n# Journal, most recent last\n{text}",
                      system=CHECKER, model=MODELS["curator"], timeout=600)
    whole = _norm(record.profile() + facts + "\n".join(e["text"] for e in journal))
    real = lambda q: bool(_norm(q)) and _norm(q)[:60] in whole  # noqa: E731
    return {"overtaken": [c for c in answer.get("overtaken") or [] if real(c.get("profile_says", "")) and real(c.get("record_shows", ""))],
            "drift": [c for c in answer.get("drift") or [] if real(c.get("profile_says", "")) and c.get("entries")]}


def related(record: Record, entry_ids: list[str]) -> dict[str, list[str]]:
    """For each due entry, the other journal entries that share its area or a person, so the
    curator reads them before saying what the record shows."""
    journal = record.journal()
    by_id = {e["front"].get("id", e["path"].stem): e for e in journal}
    out = {}
    for eid in entry_ids:
        entry = by_id.get(eid)
        if not entry:
            continue
        area, people = entry["front"].get("area"), set(entry["front"].get("people") or [])
        out[eid] = [oid for oid, other in by_id.items() if oid != eid and
                    (other["front"].get("area") == area or people & set(other["front"].get("people") or []))]
    return out


def as_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, indent=2)
