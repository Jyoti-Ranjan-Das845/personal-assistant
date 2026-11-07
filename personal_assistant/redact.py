"""Redact secrets and identity numbers from text before any agent reads it.

The person's record may hold health, money amounts and personal history, but
never secrets (passwords, keys, tokens, one-time codes) or financial and
government identifiers (card, account and routing numbers, SSN, PAN, Aadhaar,
passport numbers). This runs on everything gathered from outside: case-finder
digests, inbox items and anything the person pastes in.
"""

import re

PATTERNS = [
    ("api key", re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}\b")),
    ("api key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token", re.compile(r"\b(ghp|gho|ghs|xox[abprs])[-_][A-Za-z0-9-]{10,}\b")),
    ("token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")),
    ("password", re.compile(r"(?i)\b(password|passcode|pwd|pin)\s*[:=]\s*\S+")),
    ("one-time code", re.compile(r"(?i)\b(otp|verification code|one[- ]time code)\D{0,12}\d{4,8}\b")),
    ("card number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("Aadhaar", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
    ("IFSC or routing", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("passport number", re.compile(r"(?i)\bpassport\s*(no\.?|number|#)?\s*[:#]?\s*[A-Z]\d{7}\b")),
]


def redact(text: str) -> str:
    for label, pattern in PATTERNS:
        text = pattern.sub(f"[{label} removed]", text)
    return text
