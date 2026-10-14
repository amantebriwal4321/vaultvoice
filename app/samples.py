"""Eight sample notes spread across private, shared, and public."""

from __future__ import annotations

SAMPLES = [
    {
        "seed_id": "clinic",
        "tier": "private",
        "timestamp": "2026-10-10T15:05:00+00:00",
        "text": (
            "Call Dr. Mehta about my blood pressure meds. "
            "Clinic number is 415-555-0198. Appointment Thursday at 9am."
        ),
    },
    {
        "seed_id": "salary",
        "tier": "private",
        "timestamp": "2026-10-10T18:40:00+00:00",
        "text": (
            "Salary review landed at 142000. "
            "Email payroll at pay@northwind.io if the deposit looks short."
        ),
    },
    {
        "seed_id": "birthday",
        "tier": "private",
        "timestamp": "2026-10-11T11:20:00+00:00",
        "text": (
            "Mom's birthday is next Friday. Gift idea is the blue scarf from the market. "
            "Don't tell her."
        ),
    },
    {
        "seed_id": "standup",
        "tier": "shared",
        "timestamp": "2026-10-12T09:05:00+00:00",
        "text": "Team standup moved to 10:15 in the oak room. Bring the Q3 launch checklist.",
    },
    {
        "seed_id": "design",
        "tier": "shared",
        "timestamp": "2026-10-12T13:30:00+00:00",
        "text": (
            "Design review for the vault: new notes should stay closed until the privacy guard "
            "confirms the tier. Share this with the team."
        ),
    },
    {
        "seed_id": "oncall",
        "tier": "shared",
        "timestamp": "2026-10-13T08:15:00+00:00",
        "text": (
            "On call rotation this week: Priya covers Monday and Jordan covers Wednesday. "
            "The team should update the board."
        ),
    },
    {
        "seed_id": "howto",
        "tier": "public",
        "timestamp": "2026-10-13T16:00:00+00:00",
        "text": (
            "Public hackathon note: speak a note, pick a tier, then ask a question with an "
            "access scope. Everyone can read this."
        ),
    },
    {
        "seed_id": "filter",
        "tier": "public",
        "timestamp": "2026-10-13T16:20:00+00:00",
        "text": (
            "Public note: Qdrant payload filters keep the answer agent inside the chosen tier. "
            "Public memories are safe to quote."
        ),
    },
]


def seed_vault(vault, reset: bool = False) -> int:
    if reset:
        vault.store.reset()
    have = {note.get("seed_id") for note in vault.store.list_notes() if note.get("seed_id")}
    added = 0
    for sample in SAMPLES:
        if sample["seed_id"] in have:
            continue
        vault.store_text(
            text=sample["text"],
            tier=sample["tier"],
            source="seed",
            seed_id=sample["seed_id"],
            timestamp=sample["timestamp"],
            write_audit=False,
            use_lyzr=False,
        )
        added += 1
    return added
