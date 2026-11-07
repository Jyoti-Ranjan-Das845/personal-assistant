"""The policy engine: checks options against the hard lines and thresholds in
the person's core profile.

It is code, so the same check runs every time. A hard line is crossed when an
option contains one of the line's match_terms, or, failing that, when a model
asked one narrow question says it does and quotes the words in the option
that cross it. The code then checks that the quote really is in the option or
the situation, so the check cannot block an option on a guess. Each question
sees only the one rule, the one option and the situation, never the rest of
the conversation, so nothing the person or a message says can talk it round.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from personal_assistant.config import CHARTERS, MODELS
from personal_assistant.llm import ask_json
from personal_assistant.record import Record

CHECKER = (CHARTERS / "policy_checker.md").read_text(encoding="utf-8")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip(" .,'\"")


def crosses(rule: dict, option: str, situation: str) -> tuple[bool, str]:
    for term in rule.get("match_terms") or []:
        if term.lower() in option.lower():
            return True, f'contains "{term}"'
    question = (
        f"Hard line: {rule['rule']}\n"
        f"Situation: {situation}\n"
        f"Option: {option}\n\n"
        "Does choosing this option cross the hard line?"
    )
    answer = ask_json(question, system=CHECKER, model=MODELS["policy_checker"], timeout=300)
    if not answer.get("crosses"):
        return False, ""
    quote = _norm(str(answer.get("words_that_cross", "")))
    if quote and quote in _norm(option):  # the words must be in the option itself
        return True, f'model check: "{answer.get("words_that_cross")}"'
    return False, f"model said yes but could not point to words in the option ({answer.get('words_that_cross')!r}); not blocked"


def check_options(record: Record, situation: str, options: list[str]) -> dict:
    """Return the options that cross a hard line, and why."""
    pairs = [(option, rule) for option in options for rule in record.rules()["hard_lines"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda pair: crosses(pair[1], pair[0], situation), pairs))
    blocked: dict[str, list[dict]] = {}
    for (option, rule), (crossed, how) in zip(pairs, results):
        if crossed:
            blocked.setdefault(option, []).append({"hard_line": rule.get("id"), "rule": rule["rule"], "how": how})
    return blocked


# Any currency: a sign or code before the number, or a word after it, marks it as money at any size.
SIGN = r"(?:[$€£¥₹]|rs\.?|inr|usd|us\$|eur|gbp|aud|cad|sgd|aed)"
WORD = r"(?:rupees?|dollars?|euros?|pounds?|dirhams?)"
UNITS = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "k": 1e3, "thousand": 1e3,
         "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
AMOUNT = re.compile(
    rf"(?P<sign>{SIGN})?\s*(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>{'|'.join(sorted(UNITS, key=len, reverse=True))})?\b"
    rf"\s*(?P<word>{WORD})?"
    r"(?P<monthly>\s*(?:a|per|each|every)\s*month|\s*/\s*month|\s*monthly)?", re.I)


def amounts_in(text: str) -> list[float]:
    """Money amounts in the text, in whatever currency the person uses. A monthly amount also counts as its yearly total."""
    found = []
    text = re.sub(r"\b[A-Z]{1,3}-\d{6,8}\S*|\b\d{4}-\d{2}-\d{2}\b", " ", text)  # record ids and dates are not money
    for match in AMOUNT.finditer(text):
        value = float(match["number"].replace(",", ""))
        marked = bool(match["sign"] or match["word"])
        if match["unit"]:
            value *= UNITS[match["unit"].lower()]
        elif not marked and (value < 1000 or 1900 <= value <= 2100):  # unmarked ages, percents and years are not money
            continue
        found.append(value)
        if match["monthly"]:
            found.append(value * 12)
    return found


def stakes(record: Record, situation: str, options: list[str]) -> dict:
    threshold = record.money_threshold()
    amounts = amounts_in(situation + " " + " ".join(options))
    over = threshold is not None and any(a > threshold for a in amounts)  # "more than" the threshold, as profiles word it
    return {
        "money_threshold": threshold,
        "currency": record.currency(),
        "largest_amount_mentioned": max(amounts) if amounts else None,
        "over_threshold": over,
        "floor": "high" if over else "set by the chief of staff from reversibility (unclear counts as high)",
    }


def check_proposal(kind: str) -> dict:
    """Changes to hard lines or thresholds need the person's explicit approval of that change."""
    if kind in ("hard_line", "threshold"):
        return {"needs_explicit_hard_line_approval": True}
    return {}
