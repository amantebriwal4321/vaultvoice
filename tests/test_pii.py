from app.lyzr import parse_agent_json
from app.pii import detect_flags, redact, route_intent, suggest_tier


def test_clinic_note_is_private_and_redacted():
    text = (
        "Call Dr. Mehta about my blood pressure meds. "
        "Clinic number is 415-555-0198. Appointment Thursday at 9am."
    )
    verdict = suggest_tier(text)
    assert verdict["suggested_tier"] == "private"
    assert "phone" in verdict["pii_flags"]
    assert "health" in verdict["pii_flags"]
    hidden = redact(text)
    assert "415-555-0198" not in hidden
    assert "[phone]" in hidden
    assert "[health]" in hidden
    assert "[clinician]" in hidden
    assert "Dr. Mehta" not in hidden


def test_salary_email_and_amount():
    text = "Salary review landed at 142000. Email payroll at pay@northwind.io if the deposit looks short."
    flags = detect_flags(text)
    assert "money" in flags
    assert "email" in flags
    hidden = redact(text)
    assert "142000" not in hidden
    assert "pay@northwind.io" not in hidden
    assert "[amount]" in hidden
    assert "[email]" in hidden


def test_team_and_public_and_secret():
    assert suggest_tier("Team standup moved to 10:15 in the oak room.")["suggested_tier"] == "shared"
    assert suggest_tier("Public hackathon note: everyone can read this.")["suggested_tier"] == "public"
    birthday = suggest_tier("Mom's birthday is Friday. Don't tell her.")
    assert birthday["suggested_tier"] == "private"
    assert birthday["pii_flags"] == []


def test_router_shapes():
    assert route_intent("When is team standup?")["intent"] == "query"
    assert route_intent("Call Dr. Mehta about my blood pressure meds.")["intent"] == "store"
    assert route_intent("Don't tell her about the scarf.")["intent"] == "store"


def test_parse_agent_json_from_fence():
    raw = 'Sure\n```json\n{"intent":"query","reason":"asking"}\n```'
    assert parse_agent_json(raw)["intent"] == "query"
    assert parse_agent_json("no json here") is None
