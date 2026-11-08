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
            assert (u, v) not in [(1, 2), (2, 1), (3, 4), (4, 3)]

        for u, v in edges:
            assert (v, u) not in edges

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


def test_full_workflow_invite_links_and_kids_bonus_lottery(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_santa.db"
    seed_file = tmp_path / "test_seed.json"

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
        # 1. Check initial seeded state (draw is auto-generated on startup!)
        state = client.get("/api/state").json()
        assert state["is_live"] is False
        assert state["draw_generated"] is True
        adults = [p for p in state["participants"] if not p["is_kid"]]
        kids = [p for p in state["participants"] if p["is_kid"]]
        assert len(adults) == 6
        assert len(kids) == 3

        # 2. Fetch personal invite links as admin
        inv_res = client.post("/api/admin/invites", json={"admin_password": "tomten"})
        assert inv_res.status_code == 200
        invites = {item["id"]: item["invite_token"] for item in inv_res.json()["invites"]}
        assert len(invites) == 9

        # Verify raw DB has encrypted assignments for both adults and kids
        conn = sqlite3.connect(str(db_file))
        rows = conn.execute("SELECT name, encrypted_assignment FROM users").fetchall()
        for name, enc in rows:
            assert enc is not None
            assert enc.startswith("gAAAAAB")
            for p in state["participants"]:
                assert p["name"] not in enc

        # 3. Go Live -> wipes dev_debug_cycle from DB and API
        live_res = client.post("/api/admin/go-live", json={"admin_password": "tomten"})
        assert live_res.status_code == 200
        assert client.get("/api/state").json()["dev_debug_cycle"] == []

        # 4. First-time login WITHOUT personal invite token is blocked (prevents account hijacking!)
        p1 = adults[0]
        hijack_attempt = client.post(
            "/api/auth/login",
            json={"user_id": p1["id"], "password": "kapad"},
        )
        assert hijack_attempt.status_code == 403

        # 5. First-time login WITH personal invite token succeeds and locks account to user's PIN
        p1_token = invites[p1["id"]]
        info_res = client.get(f"/api/invite/{p1_token}")
        assert info_res.status_code == 200
        assert info_res.json()["has_account"] is False

        login_res = client.post(
            "/api/auth/login",
            json={"user_id": p1["id"], "password": "mitt-hemliga-losen", "invite_token": p1_token},
        )
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["user"]["has_drawn_lot"] is False
        assert login_data["assignment"]["target_name"] != p1["name"]
        my_alias = login_data["assignment"]["my_alias"]

        # Subsequent login works with just the user's password
        re_login = client.post(
            "/api/auth/login",
            json={"user_id": p1["id"], "password": "mitt-hemliga-losen"},
        )
        assert re_login.status_code == 200

        # Resetting PIN via personal link works and preserves the exact same match
        reset_res = client.post(
            "/api/auth/login",
            json={
                "user_id": p1["id"],
                "password": "ny-pin-9999",
                "invite_token": p1_token,
                "reset_pin": True,
            },
        )
        assert reset_res.status_code == 200
        assert reset_res.json()["assignment"]["target_name"] == login_data["assignment"]["target_name"]

        # 6. Adult draws their lot (using the new PIN)
        draw_res = client.post(
            "/api/user/draw-lot",
            json={"user_id": p1["id"], "password": "ny-pin-9999"},
        )
        assert draw_res.status_code == 200
        assert draw_res.json()["user"]["has_drawn_lot"] is True

        state_after = client.get("/api/state").json()
        alias_entry = next(
            a for a in state_after["alias_board"] if a["alias_name"] == my_alias
        )
        assert alias_entry["has_drawn"] is True

        # 7. Kid logs in via personal link and draws an optional bonus lot!
        kid1 = kids[0]
        kid_token = invites[kid1["id"]]
        kid_login = client.post(
            "/api/auth/login",
            json={"user_id": kid1["id"], "password": "1234", "invite_token": kid_token},
        )
        assert kid_login.status_code == 200
        assert kid_login.json()["assignment"]["target_name"] != kid1["name"]

        kid_draw = client.post(
            "/api/user/draw-lot",
            json={"user_id": kid1["id"], "password": "1234"},
        )
        assert kid_draw.status_code == 200
        assert kid_draw.json()["user"]["has_drawn_lot"] is True
        kid_alias = kid_draw.json()["assignment"]["my_alias"]

        state_with_kid = client.get("/api/state").json()
        kid_alias_entry = next(
            a for a in state_with_kid["alias_board"] if a["alias_name"] == kid_alias
        )
        assert kid_alias_entry["has_drawn"] is True
        assert kid_alias_entry["is_kid_bonus"] is True
        conn.close()
