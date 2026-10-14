def test_full_loop(client):
    status = client.get("/api/status")
    assert status.status_code == 200
    body = status.json()
    assert body["lyzr"] == "local-mock"
    assert body["qdrant"] == "memory"
    assert body["notes_count"] >= 8
    assert "hash-fallback" in body["embedder"]

    notes = client.get("/api/notes").json()["notes"]
    by_seed = {note["seed_id"]: note for note in notes if note.get("seed_id")}
    assert set(by_seed) >= {
        "clinic",
        "salary",
        "birthday",
        "standup",
        "design",
        "oncall",
        "howto",
        "filter",
    }
    for note in by_seed.values():
        assert note["suggested_tier"] == note["tier"]
    assert "415-555-0198" not in by_seed["clinic"]["redacted_text"]
    assert "[phone]" in by_seed["clinic"]["redacted_text"]

    before = client.get("/api/notes").json()["count"]
    stored = client.post(
        "/api/turn",
        json={
            "text": "Call Dr. Mehta about my blood pressure meds. Clinic number is 415-555-0198.",
            "tier": None,
            "scope": "me",
            "source": "typed",
        },
    )
    assert stored.status_code == 200
    saved = stored.json()
    assert saved["action"] == "store"
    assert saved["router"]["intent"] == "store"
    assert saved["reasoning_mode"] == "local-mock"
    assert saved["note"]["tier"] == "private"
    assert "phone" in saved["note"]["pii_flags"]
    assert "health" in saved["note"]["pii_flags"]
    assert saved["guard"]["mode"] == "local-mock"
    clinic_id = saved["note"]["id"]
    assert client.get("/api/notes").json()["count"] == before + 1

    team = client.post(
        "/api/turn",
        json={
            "text": "When is team standup and what should I bring?",
            "scope": "team",
            "source": "voice",
        },
    )
    assert team.status_code == 200
    asked = team.json()
    assert asked["action"] == "query"
    assert asked["router"]["intent"] == "query"
    assert asked["qdrant_filter"] == ["shared", "public"]
    assert asked["chunks"], asked
    blob = str(asked)
    assert "415-555-0198" not in blob
    assert clinic_id not in {chunk["id"] for chunk in asked["chunks"]}
    assert all(chunk["tier"] in {"shared", "public"} for chunk in asked["chunks"])
    assert any("standup" in chunk["excerpt"].lower() for chunk in asked["chunks"])
    assert client.get("/api/notes").json()["count"] == before + 1

    mine = client.post(
        "/api/turn",
        json={
            "text": "What did I say about my blood pressure and the clinic number?",
            "scope": "me",
            "source": "voice",
        },
    )
    assert mine.status_code == 200
    personal = mine.json()
    assert personal["action"] == "query"
    assert personal["qdrant_filter"] == ["private", "shared", "public"]
    private_chunks = [chunk for chunk in personal["chunks"] if chunk["tier"] == "private"]
    assert private_chunks
    assert all(chunk["redacted"] for chunk in private_chunks)
    joined = " ".join(chunk["excerpt"] for chunk in personal["chunks"]) + personal["answer"]
    assert "415-555-0198" not in joined
    assert "[phone]" in joined
    assert "[health]" in joined

    audit = client.get("/api/audit").json()["entries"]
    match = next(entry for entry in audit if entry["id"] == personal["audit_id"])
    assert match["action"] == "query"
    assert match["scope"] == "me"
    assert {chunk["id"] for chunk in match["chunks"]} == {chunk["id"] for chunk in personal["chunks"]}
    assert any(agent["name"] == "Answer" for agent in match["agents"])

    public = client.post(
        "/api/query",
        json={"text": "When is team standup and what should I bring?", "scope": "public"},
    )
    assert public.status_code == 200
    assert all(chunk["tier"] == "public" for chunk in public.json()["chunks"])
    assert "standup" not in str(public.json()["chunks"]).lower()

    override = client.post(
        "/api/turn",
        json={
            "text": "Call me at 415-555-0142 about the picnic plan.",
            "tier": "public",
            "scope": "me",
        },
    )
    assert override.status_code == 200
    forced = override.json()
    assert forced["note"]["tier"] == "public"
    assert forced["guard"]["suggested_tier"] == "private"
    assert forced["warning"]
