"""The decision procedure. The chief of staff must run it for every real
decision, and the steps are fixed in code so they cannot be skipped:

1. The policy engine removes options that cross a hard line and checks the
   money threshold.
2. The analyst prepares the evidence from the record, without a lean.
3. The advisor and the challenger each read the case in a fresh session, on
   different models, at the same time, so neither sees the other's answer.
   Each states the rule its reading rests on; the challenger adds rivals.
4. The tester lays every rule, and every reason the person gave, against
   every past case, as in Heuer's analysis of competing hypotheses.
5. Code, not a model, weighs that matrix: the rule with the least evidence
   against it gives the read, rules that hold as well but point elsewhere
   make it contested, and the confidence follows from how well the rule holds.
6. The chief of staff gets a short report built from that, not the raw readings.

Every step is written to the trace, so a failed test can be traced to the
step that went wrong.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor

from system import policy, prompts
from system.config import MODELS
from system.llm import ask, ask_json
from system.record import Record


LEVELS = ["low", "medium", "high"]
QUESTION = {
    "predict": "Question type: predict. What would the person choose? Answer by substituted judgment from the record.",
    "advise": "Question type: advise. What should the person do? Give the choice they would make and, separately, any trap clearly at work.",
}


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split()).strip(" .\"'")


def match_option(text, options: list[str]) -> str | None:
    """The option a reader meant: exact first, then one that contains or is contained by it."""
    wanted = _norm(text)
    if not wanted:
        return None
    for option in options:
        if _norm(option) == wanted:
            return option
    close = [o for o in options if _norm(o) in wanted or wanted in _norm(o)]
    return close[0] if len(close) == 1 else None


def _verdict(cell: dict) -> str:
    return _norm(cell.get("verdict")).replace(" ", "_")


def _count(rule: dict, verdict: str, present_only: bool = False) -> int:
    return sum(1 for c in rule.get("cases") or [] if _verdict(c) == verdict
               and not (present_only and c.get("feature_present") is False))


def weigh(rules: list[dict], allowed: list[str]) -> list[dict]:
    """Rank the tested rules. As in Heuer's method, the explanation with the least evidence against it wins;
    cases it leaves unexplained count next; then the cases where its feature was present and it held, which are
    the only real tests it passed; fits where the feature was absent only break ties."""
    ranked = []
    for rule in rules:
        today = rule.get("today") or {}
        predicts = match_option(today.get("predicts"), allowed)
        applies = _norm(today.get("applies")).replace(" ", "_")
        tally = {v: _count(rule, v) for v in ("fits", "contradicts", "unexplained")}
        tally["tested"] = _count(rule, "fits", present_only=True)
        if predicts is None or applies == "not_at_all" or tally["fits"] == 0:
            continue
        ranked.append({**rule, **tally, "predicts": predicts, "applies": applies})
    ranked.sort(key=lambda r: (r["contradicts"], r["unexplained"], r["applies"] != "directly", -r["tested"], -r["fits"]))
    return ranked


def as_well_supported(rule: dict, best: dict) -> bool:
    """A rival holds as well when it has no more evidence against it and passes nearly as many real tests."""
    return (rule["contradicts"] == best["contradicts"] and rule["unexplained"] == best["unexplained"]
            and rule["tested"] >= 2 and rule["tested"] >= best["tested"] - 1)


def confidence_from(best: dict | None, contested: bool, readers: list[dict], read: str, open_rival: bool = False) -> tuple[str, str]:
    """Code sets the confidence from how well the winning rule holds, so the same evidence gives the same
    confidence however the question was put. As in Heuer's method, a reading that no case contradicts cannot
    be ruled out, so while one points elsewhere the read is never high."""
    if best is None:
        return "low", "no rule in the record fits this decision, so the read is a guess"
    if contested:
        return "low", "another rule fits the record as well and points the other way"
    if best["applies"] != "directly":
        return "low", "the rule is extended from a different kind of situation"
    novel = sum(1 for r in readers if r.get("within_evidence") is False)
    if novel == len(readers):
        return "low", "both readings say this case goes beyond what the record has shown"
    if best["contradicts"] or best["unexplained"]:
        return "low", "even the best rule fails some past cases"
    if best["tested"] < 2:
        return "low", "only one past case really tests the rule"
    if best["tested"] >= 3 and not open_rival and not novel and all(_norm(r.get("choice")) == _norm(read) for r in readers):
        return "high", f"one rule held in all {best['tested']} past cases that really tested it, and both readings agree"
    why = f"one rule held in all {best['tested']} past cases that really tested it"
    if open_rival:
        why += ", but another reading that no case contradicts points the other way"
    elif novel:
        why += ", but one reading says this case goes beyond what the record has shown"
    return "medium", why


def _cells(rule: dict, verdicts: tuple[str, ...]) -> list[str]:
    return [f"{c.get('id')}: {c.get('facts')}" for c in rule.get("cases") or [] if _verdict(c) in verdicts
            and not ("fits" in verdicts and c.get("feature_present") is False)]


def _section(brief: str, heading: str) -> str:
    match = re.search(rf"##\s*{heading}[^\n]*\n(.*?)(?=\n##\s|\Z)", brief, re.S | re.I)
    text = match.group(1).strip() if match else ""
    return "" if _norm(text) in ("", "none", "none.") else text


def _stakes_line(stakes: dict) -> str:
    threshold, largest, cur = stakes.get("money_threshold"), stakes.get("largest_amount_mentioned"), stakes.get("currency", "")
    if stakes.get("over_threshold"):
        return f"High stakes: {cur}{largest:,.0f} is more than their {cur}{threshold:,.0f} line."
    if threshold is not None and largest is not None:
        return f"Not high on money: {cur}{largest:,.0f} is not more than their {cur}{threshold:,.0f} line; judge the rest by reversibility."
    return "No amount above their line; judge the stakes by reversibility (unclear counts as high)."


def report(read: str, best: dict | None, rivals: list[dict], ranked: list[dict], advisor: dict, level: str, why: str,
           mode: str, stakes: dict, brief: str, whose: str, allowed: list[str], open_rivals: list[dict] | None = None) -> dict:
    """What the chief of staff tells the person, built by code in the order it should be said."""
    other = []
    for r in rivals + (open_rivals or []):  # one entry per option, so each other reading is said once
        same = next((o for o in other if o["option"] == r["predicts"]), None)
        if same:
            same["also"] = same.get("also", []) + [r["rule"]]
        else:
            other.append({"option": r["predicts"], "rule": r["rule"], "cases_that_fit": _cells(r, ("fits",)),
                          **({} if r in rivals else {"standing": "not ruled out: no past case contradicts it, though fewer test it"})})
    first = match_option(advisor.get("choice"), allowed)
    if best and first and first != read and not any(o["option"] == first for o in other):
        weaker = next((r for r in ranked if _norm(r["rule"]) == _norm(advisor.get("rule"))), None)
        other.append({"option": first, "rule": advisor.get("rule"),
                      "why_weaker": _cells(weaker, ("contradicts", "unexplained")) if weaker else "it fits fewer past cases"})
    stated = [{"reason": r["rule"], "from": r.get("where"), "cases_it_does_not_fit": _cells(r, ("contradicts", "unexplained"))}
              for r in ranked if _norm(r.get("source")) == "the person" and (r["contradicts"] or r["unexplained"])]
    beyond = ""
    if best and best["applies"] != "directly":
        beyond = (best.get("today") or {}).get("facts", "") or "The rule comes from a different kind of situation."
    if whose:
        beyond = (f"This is {whose}'s decision. The record shows how the person chooses for themselves, not how {whose} does. " + beyond).strip()
    agreed = best is not None and first == read
    return {
        "contested": bool(rivals),
        "read": read,
        "because": best["rule"] if best else "nothing in the record decides it",
        "cases_that_fit": _cells(best, ("fits",)) if best else [],
        "cases_against": _cells(best, ("contradicts", "unexplained")) if best else [],
        "confidence": level,
        "why_this_confidence": why,
        "beyond_their_record": beyond or _section(brief, "Not covered"),
        "other_reading": other,
        "reasons_they_gave_that_do_not_fit": stated,
        "stakes": _stakes_line(stakes),
        "advice": advisor.get("advice", "") if mode == "advise" else "",
        "trap": advisor.get("blind_spot", ""),
        "how_they_would_put_it": advisor.get("how_they_would_put_it", "") if agreed else "",
        "would_change_if": advisor.get("would_change_if", "") if agreed else "",
        "options_missing_from_the_list": _section(brief, "Options missing from the list"),
        "should_not_matter": _section(brief, "Features that should not matter"),
        "facts_in_play": _section(brief, "Facts in play"),
    }


def features(brief: str) -> list[str]:
    """The candidate features the analyst listed at the end of its brief, as JSON."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", brief, re.S)
    try:
        items = json.loads(match.group(1)).get("features", []) if match else []
    except (json.JSONDecodeError, AttributeError):
        return []
    return [str(f).strip() for f in items if str(f).strip()]


def _first_lines(text: str, n: int = 2) -> str:
    lines = [l.strip(" -*") for l in text.splitlines() if l.strip(" -*")]
    return " ".join(lines[:n])


def say_in_order(rep: dict, mode: str) -> list[str]:
    """The points the chief of staff relays, in order, built by code so the same result is always told the same way."""
    lines = []
    if rep["contested"]:
        lines.append("Two readings of their record hold equally well, so say first that you cannot tell which way they would go:")
        for option, rule in [(rep["read"], rep["because"])] + [(o["option"], o["rule"]) for o in rep["other_reading"]][:2]:
            lines.append(f"- {option}, if what decides it for them is: {rule}")
        lines.append("Then ask the one question that would tell these apart: which of those things matters more to them here.")
    else:
        lines.append(f"The read: {rep['read']}.")
        if rep["cases_that_fit"]:
            seen = "; ".join(c.split(":")[0] for c in rep["cases_that_fit"][:3])
            lines.append(f"The pattern behind it: {rep['because']} (seen in {seen}).")
        for other in rep["other_reading"]:
            seen = "; ".join(c.split(":")[0] for c in other.get("cases_that_fit", [])[:3])
            lines.append(f"The other reading, in one line: {other['option']}, if {other['rule']}" + (f" (seen in {seen})" if seen else ""))
    lines.append(f"Confidence: {rep['confidence']}, because {rep['why_this_confidence']}.")
    if rep["confidence"] == "low" and rep["beyond_their_record"]:
        lines.append(f"What their record does not cover: {_first_lines(rep['beyond_their_record'])}")
    for stated in rep["reasons_they_gave_that_do_not_fit"][:2]:
        if stated["cases_it_does_not_fit"]:
            lines.append(f"A reason they gave that their record does not bear out, as a fact about the record: {stated['reason']} "
                         f"({stated['cases_it_does_not_fit'][0]})")
    if rep.get("stale_facts"):
        lines.insert(0, "Facts this rests on that are past their review date: " + "; ".join(rep["stale_facts"]) + ". If the answer "
                        "turns on them, say first that you cannot tell without current figures, and ask for them.")
    if rep["options_missing_from_the_list"]:
        lines.append(f"A way they have handled this before that is not among the options, to mention: {_first_lines(rep['options_missing_from_the_list'])}")
    if rep.get("should_not_matter"):
        lines.append(f"Something that may sway them here but should not, with the past case that shows it: {_first_lines(rep['should_not_matter'])}")
    if rep["stakes"].startswith("High stakes"):
        lines.append(rep["stakes"])
    if mode == "advise" and rep["advice"]:
        lines.append(f"Your advice, marked as yours: {rep['advice']}")
    if rep["trap"]:
        lines.append(f"One line on a trap, said once: {rep['trap']}")
    return lines


def someone_elses(record: Record, case: str, dump: str, whose: str, stakes: dict, trace) -> dict:
    """A decision that belongs to someone else is not predicted from the person's own pattern. The analyst
    sets out only what in it lands on the person, what is known and what is not."""
    brief = ask(f"{case}\n\n---\n\n{dump}", system=prompts.build("analyst", record), model=MODELS["analyst"])
    trace("analyst", {"brief": brief})
    lands = _section(brief, "What lands on the person")
    missing = _section(brief, "Not covered")
    rep = {"whose_decision": whose, "what_lands_on_the_person": lands, "not_covered": missing,
           "facts_in_play": _section(brief, "Facts in play"), "stakes": _stakes_line(stakes)}
    rep["say_in_order"] = [
        f"Say first that this is {whose}'s decision, and that their record shows how they judge things for themselves, not how "
        f"{whose} does, so it cannot say what {whose} will or should choose.",
        f"Then the part that lands on them: {_first_lines(lands, 3)}" if lands else "Then say what in it would land on them, if anything.",
        f"What is not known, with at most one question: {_first_lines(missing)}" if missing else "Ask at most one question.",
        f"Offer any view only as something they could raise with {whose}, and leave the decision with {whose} and them.",
    ]
    trace("result", {"whose_decision": whose})
    return {"mode": "someone else's decision", "report": rep, "analyst_brief": brief}


def _case(question: str, allowed: list[str], blocked: dict, notes: str, mode: str, today: str, whose: str, words: str = "") -> str:
    lines = [f"Today: {today}", QUESTION[mode], f"Decision: {question}"]
    if whose:
        lines.append(f"This decision belongs to {whose}, not to the person. Do not predict {whose}'s choice from the person's "
                     f"record. Set out under '## What lands on the person' the parts of it that would fall on the person: "
                     f"their time, money, work and the care of others, with facts.")
    lines += ["", "Options still open:"] + [f"- {o}" for o in allowed]
    if blocked:
        lines += ["", "Options removed because they cross a hard line (never choose these):"]
        lines += [f"- {o} ({', '.join(b['hard_line'] or '?' for b in why)})" for o, why in blocked.items()]
    if notes:
        lines += ["", f"Facts from the conversation and the inbox: {notes}"]
    if words:
        lines += ["", "The person's own words about it, verbatim. Take the facts from them; their mood, and any choice they "
                      f"say they lean to, are not evidence:\n{words}"]
    return "\n".join(lines)


def run(record: Record, question: str, options: list[str], notes: str = "", mode: str = "predict",
        whose: str = "", trace=None, words: str = "") -> dict:
    trace = trace or (lambda step, data: None)
    options = [o.strip() for o in options if o.strip()]
    mode = mode if mode in QUESTION else "predict"
    person = _norm(record.person().get("name"))
    whose = "" if _norm(whose) in ("", "theirs", "hers", "his", "mine", "the person", person) else whose.strip()

    blocked = policy.check_options(record, question + " " + notes, options)
    stakes = policy.stakes(record, question, options)  # the amount being decided, never background figures in the notes
    allowed = [o for o in options if o not in blocked]
    trace("policy", {"blocked": blocked, "stakes": stakes})
    if not allowed:
        return {"stakes": stakes, "blocked": blocked, "error": "every option crosses a hard line; ask the person for other options"}

    case = _case(question, allowed, blocked, notes, mode, record.today.isoformat(), whose, words)
    dump = record.dump()
    if whose:
        return someone_elses(record, case, dump, whose, stakes, trace)
    brief = ask(f"{case}\n\n---\n\n{dump}", system=prompts.build("analyst", record), model=MODELS["analyst"])
    trace("analyst", {"brief": brief})

    reading_input = f"{case}\n\n---\n\nAnalyst's brief:\n{brief}\n\n---\n\n{dump}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        advisor = pool.submit(ask_json, reading_input, system=prompts.build("advisor", record), model=MODELS["advisor"])
        challenger = pool.submit(ask_json, reading_input, system=prompts.build("challenger", record), model=MODELS["challenger"])
        advisor, challenger = advisor.result(), challenger.result()
    if mode == "advise" and not str(advisor.get("advice", "")).strip():  # a should-question always gets advice
        advisor = ask_json(reading_input + "\n\nThis is a should-question and your reply must fill advice: what you would "
                           "recommend they do, and why, in a line.", system=prompts.build("advisor", record), model=MODELS["advisor"])
    trace("advisor", advisor)
    trace("challenger", challenger)

    proposed = [{"rule": advisor.get("rule"), "source": "advisor"}, {"rule": challenger.get("rule"), "source": "challenger"}]
    proposed += [{"rule": r.get("rule"), "source": "challenger"} for r in challenger.get("rival_rules") or [] if isinstance(r, dict)]
    proposed = [p for p in proposed if _norm(p["rule"])]
    table = features(brief)[:8]  # each gets a rule, so the set never depends on who thought of what; few, so none fits by chance
    try:
        matrix = ask_json(f"{case}\n\nRules to test:\n{json.dumps(proposed, ensure_ascii=False, indent=1)}\n\n"
                          f"Features from the analyst's table; make one rule for each, with source \"the analyst's table\":\n"
                          f"{json.dumps(table, ensure_ascii=False, indent=1)}\n\n---\n\n"
                          f"Analyst's brief:\n{brief}\n\n---\n\n{dump}",
                          system=prompts.build("tester", record), model=MODELS["tester"])
    except Exception as error:  # the procedure still answers, at low confidence, if the tester fails
        matrix = {"rules": [], "error": str(error)}
    trace("tester", matrix)
    built = sum(1 for r in matrix.get("rules") or [] if "table" in _norm(r.get("source")))
    if built < len(table):
        trace("tester_gap", {"features": len(table), "rules_from_table": built})

    readers = [advisor, challenger]
    ranked = weigh(matrix.get("rules") or [], allowed)
    best = ranked[0] if ranked else None
    rivals = [r for r in ranked[1:] if r["predicts"] != best["predicts"] and as_well_supported(r, best)] if best else []
    read = best["predicts"] if best else (match_option(advisor.get("choice"), allowed) or allowed[0])
    open_rivals = [r for r in ranked[1:] if best and r["predicts"] != best["predicts"] and r not in rivals
                   and r["contradicts"] == 0 and r["unexplained"] == 0 and r["tested"] >= 1][:2]
    level, why = confidence_from(best, bool(rivals), readers, read, bool(open_rivals))
    trace("weighing", {"ranked": [{k: r[k] for k in ("rule", "predicts", "tested", "fits", "contradicts", "unexplained", "applies")} for r in ranked],
                       "read": read, "contested": bool(rivals), "confidence": level})

    rep = report(read, best, rivals, ranked, advisor, level, why, mode, stakes, brief, whose, allowed, open_rivals)
    rep["stale_facts"] = [f"{f.get('key')} = {f.get('value')} (as of {f.get('as_of')})" for f in record.stale_facts()
                          if str(f.get("key", "")) in brief]
    rep["say_in_order"] = say_in_order(rep, mode)
    result = {
        "mode": mode,
        "report": rep,
        "how_to_use": "Relay say_in_order: keep every point and its order, put it in their words and in the style their "
                      "profile asks for, and add no reading of your own. The confidence is set by code; use it as given.",
        "removed_by_hard_lines": blocked,
        "options_open": allowed,
        "analyst_brief": brief,
    }
    trace("result", {"read": read, "confidence": level})
    return result


def as_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
