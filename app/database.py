import hashlib
import json
import secrets
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


def generate_invite_token() -> str:
    return secrets.token_urlsafe(12)


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
                invite_token TEXT UNIQUE NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT DEFAULT NULL,
                encrypted_assignment TEXT DEFAULT NULL,
                token_encrypted_assignment TEXT DEFAULT NULL,
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
                has_drawn INTEGER NOT NULL DEFAULT 0,
                is_kid_bonus INTEGER NOT NULL DEFAULT 0
            );
            """
        )

        # Ensure migration if older table existed without invite_token or is_kid_bonus
        user_cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "invite_token" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN invite_token TEXT")
            for row in conn.execute("SELECT id FROM users").fetchall():
                conn.execute(
                    "UPDATE users SET invite_token = ? WHERE id = ?",
                    (generate_invite_token(), row["id"]),
                )
        if "token_encrypted_assignment" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN token_encrypted_assignment TEXT")

        alias_cols = [r["name"] for r in conn.execute("PRAGMA table_info(alias_board)").fetchall()]
        if "is_kid_bonus" not in alias_cols:
            conn.execute("ALTER TABLE alias_board ADD COLUMN is_kid_bonus INTEGER NOT NULL DEFAULT 0")

        if not get_setting(conn, "server_salt"):
            set_setting(conn, "server_salt", generate_salt())

        target_seed = seed_path or SEED_PATH
        current_seed_hash = ""
        if target_seed.exists():
            current_seed_hash = hashlib.sha256(target_seed.read_bytes()).hexdigest()

        if not get_setting(conn, "initialized"):
            load_seed_into_db(conn, target_seed)
            set_setting(conn, "initialized", "1")
            set_setting(conn, "seed_hash", current_seed_hash)
        elif (
            current_seed_hash
            and get_setting(conn, "seed_hash") != current_seed_hash
            and get_setting(conn, "is_live", "0") == "0"
        ):
            # Automatically reload seed.json if it changed in git and the draw is not locked live yet
            load_seed_into_db(conn, target_seed)
            set_setting(conn, "seed_hash", current_seed_hash)
    conn.close()


def load_seed_into_db(conn: sqlite3.Connection, seed_path: Path) -> None:
    if seed_path.exists():
        data = json.loads(seed_path.read_text(encoding="utf-8"))
    else:
        data = {
            "event_title": "Julklappsspelet",
            "budget_info": "Secret Santa för familjen",
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
                "Saffransdraken",
                "Kanelbullespion",
            ],
        }

    conn.execute("DELETE FROM alias_board")
    conn.execute("DELETE FROM exclusions")
    conn.execute("DELETE FROM users")

    set_setting(conn, "event_title", data.get("event_title", "Julklappsspelet"))
    set_setting(conn, "budget_info", data.get("budget_info", "Secret Santa för familjen"))
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
        token = p.get("invite_token", "").strip() or generate_invite_token()
        cur = conn.execute(
            "INSERT INTO users (name, is_kid, wishlist, invite_token, password_salt) VALUES (?, ?, ?, ?, ?)",
            (name, is_kid, wishlist, token, generate_salt()),
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
    users = conn.execute("SELECT id, name, is_kid, wishlist, invite_token FROM users ORDER BY is_kid ASC, id ASC").fetchall()
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
        "event_title": get_setting(conn, "event_title", "Julklappsspelet"),
        "budget_info": get_setting(conn, "budget_info", "Secret Santa för familjen"),
        "participants": [
            {
                "name": u["name"],
                "is_kid": bool(u["is_kid"]),
                "wishlist": u["wishlist"],
                "invite_token": u["invite_token"],
            }
            for u in users
        ],
        "exclusions": exclusions,
        "aliases": aliases,
    }
