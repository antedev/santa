import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import DB_PATH, DEV_MODE_ENV, SEED_PATH
from app.crypto import generate_salt


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = db_path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def init_db(db_path: Optional[Path] = None, seed_path: Optional[Path] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL COLLATE NOCASE,
                is_kid INTEGER NOT NULL DEFAULT 0,
                wishlist TEXT NOT NULL DEFAULT '',
                password_salt TEXT NOT NULL,
                password_hash TEXT DEFAULT NULL,
                encrypted_assignment TEXT DEFAULT NULL,
                is_password_encrypted INTEGER NOT NULL DEFAULT 0,
                has_drawn_lot INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS exclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_a_id INTEGER NOT NULL,
                user_b_id INTEGER NOT NULL,
                FOREIGN KEY(user_a_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(user_b_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS alias_board (
                alias_name TEXT PRIMARY KEY,
                has_drawn INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS kid_gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_user_id INTEGER NOT NULL,
                giver_label TEXT NOT NULL,
                gift_note TEXT NOT NULL DEFAULT '',
                owner_tag TEXT NOT NULL,
                FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

        if not get_setting(conn, "server_salt"):
            set_setting(conn, "server_salt", generate_salt())

        if not get_setting(conn, "initialized"):
            load_seed_into_db(conn, seed_path or SEED_PATH)
            set_setting(conn, "initialized", "1")
    conn.close()


def load_seed_into_db(conn: sqlite3.Connection, seed_path: Path) -> None:
    if seed_path.exists():
        data = json.loads(seed_path.read_text(encoding="utf-8"))
    else:
        data = {
            "event_title": "Julklappsspelet – Secret Santa",
            "budget_info": "Ca 300 kr per julklapp",
            "participants": [],
            "exclusions": [],
            "aliases": [
                "Glittrande Renen",
                "Smygande Tomten",
                "Knäckhäxan",
                "Rimstjärnan",
                "Pepparkaksriddaren",
                "Snöflingeprinsen",
                "Polkagrisräven",
                "Julmustbaronen",
            ],
        }

    conn.execute("DELETE FROM kid_gifts")
    conn.execute("DELETE FROM alias_board")
    conn.execute("DELETE FROM exclusions")
    conn.execute("DELETE FROM users")

    set_setting(conn, "event_title", data.get("event_title", "Julklappsspelet – Secret Santa"))
    set_setting(conn, "budget_info", data.get("budget_info", "Ca 300 kr per julklapp"))
    set_setting(conn, "draw_generated", "0")
    set_setting(conn, "is_live", "0")
    set_setting(conn, "dev_mode_enabled", "1" if DEV_MODE_ENV else "0")
    set_setting(conn, "alias_pool_json", json.dumps(data.get("aliases", []), ensure_ascii=False))
    set_setting(conn, "alias_cycle_json", "[]")
    set_setting(conn, "dev_debug_cycle_json", "[]")
    set_setting(conn, "server_salt", generate_salt())

    name_to_id: Dict[str, int] = {}
    for p in data.get("participants", []):
        name = p["name"].strip()
        if not name:
            continue
        is_kid = 1 if p.get("is_kid", False) else 0
        wishlist = p.get("wishlist", "").strip()
        cur = conn.execute(
            "INSERT INTO users (name, is_kid, wishlist, password_salt) VALUES (?, ?, ?, ?)",
            (name, is_kid, wishlist, generate_salt()),
        )
        name_to_id[name.lower()] = cur.lastrowid

    for pair in data.get("exclusions", []):
        if len(pair) == 2:
            a_id = name_to_id.get(pair[0].strip().lower())
            b_id = name_to_id.get(pair[1].strip().lower())
            if a_id and b_id and a_id != b_id:
                u1, u2 = min(a_id, b_id), max(a_id, b_id)
                exists = conn.execute(
                    "SELECT 1 FROM exclusions WHERE user_a_id = ? AND user_b_id = ?",
                    (u1, u2),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO exclusions (user_a_id, user_b_id) VALUES (?, ?)",
                        (u1, u2),
                    )


def export_current_to_seed_dict(conn: sqlite3.Connection) -> Dict[str, Any]:
    users = conn.execute("SELECT id, name, is_kid, wishlist FROM users ORDER BY is_kid ASC, id ASC").fetchall()
    id_to_name = {u["id"]: u["name"] for u in users}
    exclusions_rows = conn.execute("SELECT user_a_id, user_b_id FROM exclusions ORDER BY id ASC").fetchall()
    exclusions: List[List[str]] = []
    for row in exclusions_rows:
        na = id_to_name.get(row["user_a_id"])
        nb = id_to_name.get(row["user_b_id"])
        if na and nb:
            exclusions.append([na, nb])

    aliases = json.loads(get_setting(conn, "alias_pool_json", "[]"))
    return {
        "event_title": get_setting(conn, "event_title", "Julklappsspelet – Secret Santa"),
        "budget_info": get_setting(conn, "budget_info", "Ca 300 kr per julklapp"),
        "participants": [
            {
                "name": u["name"],
                "is_kid": bool(u["is_kid"]),
                "wishlist": u["wishlist"],
            }
            for u in users
        ],
        "exclusions": exclusions,
        "aliases": aliases,
    }


def make_owner_tag(server_salt: str, user_id: int) -> str:
    return hashlib.sha256(f"kid-gift-owner:{server_salt}:{user_id}".encode("utf-8")).hexdigest()[:24]
