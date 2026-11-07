import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.matcher import MatchingError, find_single_cycle


def test_single_cycle_no_two_loops_and_exclusions():
    ids = [1, 2, 3, 4, 5, 6]
    exclusions = [(1, 2), (3, 4)]

    for seed in range(30):
        cycle = find_single_cycle(ids, exclusions, seed=str(seed))
        assert len(cycle) == 6
        assert set(cycle) == set(ids)

        n = len(cycle)
        edges = set()
        for i in range(n):
            u = cycle[i]
            v = cycle[(i + 1) % n]
            assert u != v
            edges.add((u, v))
            # Check exclusions
            assert (u, v) not in [(1, 2), (2, 1), (3, 4), (4, 3)]

        # Verify no 2-person loop (A -> B and B -> A)
        for u, v in edges:
            assert (v, u) not in edges

        # Verify walking the cycle visits all 6 nodes before returning to start
        curr = cycle[0]
        next_map = {cycle[i]: cycle[(i + 1) % n] for i in range(n)}
        visited = []
        for _ in range(n):
            visited.append(curr)
            curr = next_map[curr]
        assert curr == cycle[0]
        assert len(set(visited)) == n


def test_less_than_three_adults_rejected():
    with pytest.raises(MatchingError):
        find_single_cycle([1, 2], [])


def test_full_workflow_and_admin_blindness(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_santa.db"
    seed_file = tmp_path / "test_seed.json"

    # Copy project seed.json to temp seed_file
    orig_seed = Path(__file__).resolve().parent.parent / "seed.json"
    seed_file.write_text(orig_seed.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setenv("SECRET_SANTA_DB", str(db_file))
    monkeypatch.setenv("SECRET_SANTA_SEED", str(seed_file))
    monkeypatch.setenv("SECRET_SANTA_DEV_MODE", "1")

    import importlib
    import app.config
    import app.database
    import app.main

    importlib.reload(app.config)
    importlib.reload(app.database)
    importlib.reload(app.main)

    with TestClient(app.main.app) as client:
        # 1. Check initial seeded state
        state = client.get("/api/state").json()
        assert state["is_live"] is False
        assert state["draw_generated"] is False
        adults = [p for p in state["participants"] if not p["is_kid"]]
        kids = [p for p in state["participants"] if p["is_kid"]]
        assert len(adults) == 6
        assert len(kids) == 2

        # 2. Pre-generate draw in advance with a seed
        gen_res = client.post(
            "/api/admin/generate-draw",
            json={"admin_password": "tomten", "seed": "julafton2026"},
        )
        assert gen_res.status_code == 200
        assert gen_res.json()["adult_count"] == 6

        # In dev mode before going live, dev_debug_cycle is visible for verification
        state = client.get("/api/state").json()
        assert state["draw_generated"] is True
        assert len(state["alias_cycle"]) == 6
        assert len(state["dev_debug_cycle"]) == 6

        # Verify raw DB has encrypted assignments (not plain text names)
        conn = sqlite3.connect(str(db_file))
        rows = conn.execute("SELECT name, encrypted_assignment FROM users WHERE is_kid = 0").fetchall()
        for name, enc in rows:
            assert enc is not None
            assert enc.startswith("gAAAAAB")
            for a in adults:
                assert a["name"] not in enc

        # 3. Go Live -> wipes dev_debug_cycle from DB and API
        live_res = client.post("/api/admin/go-live", json={"admin_password": "tomten"})
        assert live_res.status_code == 200

        state_live = client.get("/api/state").json()
        assert state_live["is_live"] is True
        assert state_live["dev_mode_enabled"] is False
        assert state_live["dev_debug_cycle"] == []

        raw_dev_json = conn.execute(
            "SELECT value FROM settings WHERE key = 'dev_debug_cycle_json'"
        ).fetchone()[0]
        assert raw_dev_json == "[]"

        # 4. Participant 1 logs in for the first time & sets password
        p1 = adults[0]
        login_res = client.post(
            "/api/auth/login",
            json={"user_id": p1["id"], "password": "mitt-hemliga-losen"},
        )
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["user"]["has_drawn_lot"] is False
        assert login_data["assignment"]["target_name"] != p1["name"]
        my_alias = login_data["assignment"]["my_alias"]

        # Verify wrong password fails
        bad_login = client.post(
            "/api/auth/login",
            json={"user_id": p1["id"], "password": "fel-losen"},
        )
        assert bad_login.status_code == 401

        # Verify DB row is now password-encrypted
        is_pw_enc = conn.execute(
            "SELECT is_password_encrypted FROM users WHERE id = ?", (p1["id"],)
        ).fetchone()[0]
        assert is_pw_enc == 1
        conn.close()

        # 5. Participant 1 clicks "Dra min julklappslott!" (Lottery illusion)
        draw_res = client.post(
            "/api/user/draw-lot",
            json={"user_id": p1["id"], "password": "mitt-hemliga-losen"},
        )
        assert draw_res.status_code == 200
        assert draw_res.json()["user"]["has_drawn_lot"] is True

        # Check public alias board shows my_alias has drawn
        state_after = client.get("/api/state").json()
        alias_entry = next(
            a for a in state_after["alias_board"] if a["alias_name"] == my_alias
        )
        assert alias_entry["has_drawn"] is True

        # 6. Kids bonus gift signup & deletion
        kid1 = kids[0]
        gift_res = client.post(
            "/api/user/kid-gift",
            json={
                "user_id": p1["id"],
                "password": "mitt-hemliga-losen",
                "recipient_user_id": kid1["id"],
                "giver_mode": "alias",
                "gift_note": "Har köpt LEGO!",
            },
        )
        assert gift_res.status_code == 200

        state_with_gift = client.get("/api/state").json()
        assert len(state_with_gift["kid_gifts"]) == 1
        pledge = state_with_gift["kid_gifts"][0]
        assert pledge["recipient_name"] == kid1["name"]
        assert my_alias in pledge["giver_label"]
        assert pledge["gift_note"] == "Har köpt LEGO!"

        del_res = client.delete(
            f"/api/user/kid-gift/{pledge['id']}",
            params={"user_id": p1["id"], "password": "mitt-hemliga-losen"},
        )
        assert del_res.status_code == 200
        assert len(client.get("/api/state").json()["kid_gifts"]) == 0
