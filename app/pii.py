"""Local privacy scan. Deterministic on purpose, so a model cannot skip it."""

from __future__ import annotations

import re

PHONE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-])?(?:\(?\d{3}\)?[\s.-])\d{3}[\s.-]\d{4}(?!\d)"
)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
LONG_NUMBER = re.compile(r"(?<!\d)\d{5,}(?!\d)")
CLINICIAN = re.compile(r"\bDr\.?\s+[A-Z][a-z]+\b")
HEALTH_PHRASE = re.compile(
    r"\b(blood pressure(?: meds| medication| medications)?|medications?|meds|"
    r"prescriptions?|diagnos(?:is|es|ed)|therap(?:y|ies)|symptoms?)\b",
    re.I,
)
HEALTH_FLAG = re.compile(
    r"\b(blood pressure|diagnos\w*|medications?|meds|prescriptions?|therap\w*|"
    r"symptoms?|clinic|doctor|hospital|patient)\b",
    re.I,
)
MONEY_FLAG = re.compile(
    r"\b(salary|paycheck|payroll|invoice|bank account|routing number|bonus|compensation)\b",
    re.I,
)
SECRET = re.compile(
    r"\b(confidential|secret|password|do not tell|don'?t tell)\b",
    re.I,
)
TEAM = re.compile(
    r"\b(team|standup|sprint|on call|launch checklist|design review)\b",
    re.I,
)
PUBLIC = re.compile(r"\b(public|announcement|hackathon)\b", re.I)

TIER_RANK = {"public": 0, "shared": 1, "private": 2}
TIERS = ("private", "shared", "public")


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def detect_flags(text: str) -> list[str]:
    flags: list[str] = []
    if PHONE.search(text):
        flags.append("phone")
    if EMAIL.search(text):
        flags.append("email")
    if SSN.search(text):
        flags.append("ssn")
    if HEALTH_FLAG.search(text) or CLINICIAN.search(text):
        flags.append("health")
    if MONEY.search(text) or MONEY_FLAG.search(text):
        flags.append("money")
    return flags


def suggest_tier(text: str) -> dict:
    """Rule based Privacy Guard used as the mock and as a safety net."""
    flags = detect_flags(text)
    if flags:
        return {
            "suggested_tier": "private",
            "pii_flags": flags,
            "reason": "PII detected: " + ", ".join(flags) + ".",
        }
    if SECRET.search(text):
        return {
            "suggested_tier": "private",
            "pii_flags": [],
            "reason": "Wording marks this as something to keep closed.",
        }
    if TEAM.search(text):
        return {
            "suggested_tier": "shared",
            "pii_flags": [],
            "reason": "Team operations language, and no PII found.",
        }
    if PUBLIC.search(text):
        return {
            "suggested_tier": "public",
            "pii_flags": [],
            "reason": "Reads as public information, and no PII found.",
        }
    return {
        "suggested_tier": "private",
        "pii_flags": [],
        "reason": "No team or public signal, so the guard stays closed.",
    }


def redact(text: str) -> str:
    """Strip concrete PII. Health phrases and clinician names go too."""
    cleaned = CLINICIAN.sub("[clinician]", text)
    cleaned = HEALTH_PHRASE.sub("[health]", cleaned)
    cleaned = EMAIL.sub("[email]", cleaned)
    cleaned = SSN.sub("[ssn]", cleaned)
    cleaned = PHONE.sub("[phone]", cleaned)
    cleaned = MONEY.sub("[amount]", cleaned)
    cleaned = LONG_NUMBER.sub("[amount]", cleaned)
    return cleaned


def stricter(left: str, right: str) -> str:
    if left not in TIER_RANK:
        return right if right in TIER_RANK else "private"
    if right not in TIER_RANK:
        return left
    return left if TIER_RANK[left] >= TIER_RANK[right] else right


def route_intent(text: str) -> dict:
    stripped = text.strip()
    starter = re.compile(
        r"(?i)^(what|when|where|who|why|how|which|tell me|show me|find|search|recall|list|did i|do i|can i|could i)\b"
    )
    if "?" in stripped or starter.search(stripped):
        return {"intent": "query", "reason": "Question shape, so this is a retrieval."}
    return {"intent": "store", "reason": "Statement shape, so this is a note to store."}
