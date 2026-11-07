import json
import random
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ADMIN_PASSWORD, DEV_MODE_ENV, SEED_PATH
from app.crypto import (
    decrypt_payload,
    decrypt_preclaim_assignment,
    encrypt_payload,
    encrypt_preclaim_assignment,
    generate_salt,
    hash_password,
    verify_password,
)
from app.database import (
    export_current_to_seed_dict,
    get_connection,
    get_setting,
    init_db,
    load_seed_into_db,
    make_owner_tag,
    set_setting,
)
from app.matcher import MatchingError, assign_aliases, find_single_cycle


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Julklappsspelet – Secret Santa", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Pydantic Models ---

class AdminAuthMixin(BaseModel):
    admin_password: str = Field(default="")


class UpdateSettingsRequest(AdminAuthMixin):
    event_title: str
    budget_info: str
    aliases: List[str]


class ParticipantCreateRequest(AdminAuthMixin):
    name: str
    is_kid: bool = False
    wishlist: str = ""


class ParticipantUpdateRequest(AdminAuthMixin):
    name: str
    is_kid: bool = False
    wishlist: str = ""


class ExclusionCreateRequest(AdminAuthMixin):
    user_a_id: int
    user_b_id: int


class GenerateDrawRequest(AdminAuthMixin):
    seed: Optional[str] = None
    custom_cycle_user_ids: Optional[List[int]] = None


class LoginRequest(BaseModel):
    user_id: int
    password: str


class WishlistUpdateRequest(BaseModel):
    user_id: int
    password: str
    wishlist: str


class KidGiftCreateRequest(BaseModel):
    user_id: int
    password: str
    recipient_user_id: int
    giver_mode: str = "secret"  # "secret" | "alias" | "name"
    gift_note: str = ""


class KidGiftDeleteRequest(BaseModel):
    user_id: int
    password: str


# --- Helper functions ---

def _check_admin(provided_password: str) -> None:
    if provided_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Fel administratörslösenord.")


def _ensure_not_live(conn) -> None:
    if get_setting(conn, "is_live", "0") == "1":
        raise HTTPException(
            status_code=400,
            detail="Lottningen är redan låst och live! Återställ från seed om du vill börja om.",
        )


def _perform_draw_generation(
    conn,
    seed: Optional[str] = None,
    custom_cycle_user_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    adults = conn.execute(
        "SELECT id, name FROM users WHERE is_kid = 0 ORDER BY id ASC"
    ).fetchall()
    adult_ids = [r["id"] for r in adults]
    id_to_name = {r["id"]: r["name"] for r in adults}

    exclusions_rows = conn.execute("SELECT user_a_id, user_b_id FROM exclusions").fetchall()
    excluded_pairs: List[Tuple[int, int]] = [
        (r["user_a_id"], r["user_b_id"]) for r in exclusions_rows
    ]

    if custom_cycle_user_ids:
        if sorted(custom_cycle_user_ids) != sorted(adult_ids):
            raise MatchingError("Den manuella kedjan måste innehålla exakt alla vuxna deltagare.")
        if len(custom_cycle_user_ids) < 3:
            raise MatchingError("Det behövs minst 3 vuxna deltagare i huvudlottningen.")
        forbidden = set()
        for a, b in excluded_pairs:
            forbidden.add((a, b))
            forbidden.add((b, a))
        n = len(custom_cycle_user_ids)
        for i in range(n):
            u = custom_cycle_user_ids[i]
            v = custom_cycle_user_ids[(i + 1) % n]
            if (u, v) in forbidden:
                raise MatchingError(
                    f"Den valda kedjan bryter mot undantagsregeln mellan {id_to_name[u]} och {id_to_name[v]}."
                )
        cycle_ids = list(custom_cycle_user_ids)
    else:
        cycle_ids = find_single_cycle(adult_ids, excluded_pairs, seed=seed)

    aliases_pool = json.loads(get_setting(conn, "alias_pool_json", "[]"))
    user_aliases = assign_aliases(cycle_ids, aliases_pool, seed=seed)

    # Rotate server_salt so preclaim keys are fresh
    server_salt = generate_salt()
    set_setting(conn, "server_salt", server_salt)

    # Reset passwords and draw status so pre-claim encryption is consistent
    for uid in adult_ids:
        conn.execute(
            "UPDATE users SET password_hash = NULL, password_salt = ?, is_password_encrypted = 0, has_drawn_lot = 0 WHERE id = ?",
            (generate_salt(), uid),
        )
    conn.execute(
        "UPDATE users SET password_hash = NULL, is_password_encrypted = 0, has_drawn_lot = 0, encrypted_assignment = NULL WHERE is_kid = 1"
    )

    n = len(cycle_ids)
    alias_cycle: List[str] = []
    dev_debug_cycle: List[Dict[str, Any]] = []

    for i in range(n):
        giver_id = cycle_ids[i]
        target_id = cycle_ids[(i + 1) % n]
        giver_alias = user_aliases[giver_id]
        target_alias = user_aliases[target_id]
        alias_cycle.append(giver_alias)

        user_row = conn.execute(
            "SELECT password_salt FROM users WHERE id = ?", (giver_id,)
        ).fetchone()
        payload = {
            "target_id": target_id,
            "target_name": id_to_name[target_id],
            "my_alias": giver_alias,
            "target_alias": target_alias,
        }
        ciphertext = encrypt_preclaim_assignment(
            payload, server_salt, giver_id, user_row["password_salt"]
        )
        conn.execute(
            "UPDATE users SET encrypted_assignment = ?, is_password_encrypted = 0, has_drawn_lot = 0 WHERE id = ?",
            (ciphertext, giver_id),
        )

        dev_debug_cycle.append(
            {
                "giver_id": giver_id,
                "giver_name": id_to_name[giver_id],
                "giver_alias": giver_alias,
                "target_id": target_id,
                "target_name": id_to_name[target_id],
                "target_alias": target_alias,
            }
        )

    # Populate alias_board in shuffled order so row order doesn't match cycle order
    conn.execute("DELETE FROM alias_board")
    shuffled_aliases = list(alias_cycle)
    random.shuffle(shuffled_aliases)
    for alias in shuffled_aliases:
        conn.execute(
            "INSERT INTO alias_board (alias_name, has_drawn) VALUES (?, 0)",
            (alias,),
        )

    set_setting(conn, "alias_cycle_json", json.dumps(alias_cycle, ensure_ascii=False))
    set_setting(conn, "draw_generated", "1")

    dev_enabled = get_setting(conn, "dev_mode_enabled", "1" if DEV_MODE_ENV else "0") == "1" and DEV_MODE_ENV
    if dev_enabled:
        set_setting(conn, "dev_debug_cycle_json", json.dumps(dev_debug_cycle, ensure_ascii=False))
    else:
        set_setting(conn, "dev_debug_cycle_json", "[]")

    return {
        "alias_cycle": alias_cycle,
        "adult_count": n,
    }


def _authenticate_user(conn, user_id: int, password: str):
    password_clean = password.strip()
    if len(password_clean) < 2:
        raise HTTPException(status_code=400, detail="Lösenordet/PIN-koden måste vara minst 2 tecken.")

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Deltagaren hittades inte.")

    server_salt = get_setting(conn, "server_salt")

    if user["password_hash"] is None:
        # First-time registration: set user's password and re-encrypt their pre-generated assignment
        pw_hash = hash_password(password_clean, user["password_salt"])
        if user["encrypted_assignment"] and not user["is_password_encrypted"]:
            plain_payload = decrypt_preclaim_assignment(
                user["encrypted_assignment"],
                server_salt,
                user["id"],
                user["password_salt"],
            )
            re_encrypted = encrypt_payload(plain_payload, password_clean, user["password_salt"])
            conn.execute(
                "UPDATE users SET password_hash = ?, encrypted_assignment = ?, is_password_encrypted = 1 WHERE id = ?",
                (pw_hash, re_encrypted, user["id"]),
            )
        else:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (pw_hash, user["id"]),
            )
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    else:
        if not verify_password(password_clean, user["password_salt"], user["password_hash"]):
            raise HTTPException(status_code=401, detail="Fel lösenord eller PIN-kod! Försök igen.")
        # Upgrade preclaim encryption if draw was generated after password was set
        if user["encrypted_assignment"] and not user["is_password_encrypted"]:
            plain_payload = decrypt_preclaim_assignment(
                user["encrypted_assignment"],
                server_salt,
                user["id"],
                user["password_salt"],
            )
            re_encrypted = encrypt_payload(plain_payload, password_clean, user["password_salt"])
            conn.execute(
                "UPDATE users SET encrypted_assignment = ?, is_password_encrypted = 1 WHERE id = ?",
                (re_encrypted, user["id"]),
            )
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    return user, password_clean


def _build_user_session_response(conn, user, password_clean: str) -> Dict[str, Any]:
    assignment = None
    if not user["is_kid"] and user["encrypted_assignment"]:
        decrypted = decrypt_payload(
            user["encrypted_assignment"], password_clean, user["password_salt"]
        )
        target_row = conn.execute(
            "SELECT id, name, wishlist FROM users WHERE id = ?",
            (decrypted["target_id"],),
        ).fetchone()
        assignment = {
            "target_id": decrypted["target_id"],
            "target_name": target_row["name"] if target_row else decrypted["target_name"],
            "target_wishlist": target_row["wishlist"] if target_row else "",
            "my_alias": decrypted["my_alias"],
            "target_alias": decrypted["target_alias"],
        }

    server_salt = get_setting(conn, "server_salt")
    return {
        "user": {
            "id": user["id"],
            "name": user["name"],
            "is_kid": bool(user["is_kid"]),
            "wishlist": user["wishlist"],
            "has_drawn_lot": bool(user["has_drawn_lot"]),
            "owner_tag": make_owner_tag(server_salt, user["id"]),
        },
        "assignment": assignment,
    }


# --- Routes ---

@app.get("/")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/state")
def get_state():
    conn = get_connection()
    try:
        users_rows = conn.execute(
            "SELECT id, name, is_kid, wishlist, password_hash IS NOT NULL AS has_account, has_drawn_lot "
            "FROM users ORDER BY is_kid ASC, name COLLATE NOCASE ASC"
        ).fetchall()

        id_to_name = {r["id"]: r["name"] for r in users_rows}
        exclusions_rows = conn.execute(
            "SELECT id, user_a_id, user_b_id FROM exclusions ORDER BY id ASC"
        ).fetchall()
        exclusions = [
            {
                "id": r["id"],
                "user_a_id": r["user_a_id"],
                "user_a_name": id_to_name.get(r["user_a_id"], "?"),
                "user_b_id": r["user_b_id"],
                "user_b_name": id_to_name.get(r["user_b_id"], "?"),
            }
            for r in exclusions_rows
        ]

        alias_board_rows = conn.execute(
            "SELECT alias_name, has_drawn FROM alias_board ORDER BY alias_name COLLATE NOCASE ASC"
        ).fetchall()
        alias_board = [
            {"alias_name": r["alias_name"], "has_drawn": bool(r["has_drawn"])}
            for r in alias_board_rows
        ]

        kid_gifts_rows = conn.execute(
            "SELECT id, recipient_user_id, giver_label, gift_note, owner_tag FROM kid_gifts ORDER BY id ASC"
        ).fetchall()
        kid_gifts = [
            {
                "id": r["id"],
                "recipient_user_id": r["recipient_user_id"],
                "recipient_name": id_to_name.get(r["recipient_user_id"], "?"),
                "giver_label": r["giver_label"],
                "gift_note": r["gift_note"],
                "owner_tag": r["owner_tag"],
            }
            for r in kid_gifts_rows
        ]

        is_live = get_setting(conn, "is_live", "0") == "1"
        dev_mode_enabled = (
            DEV_MODE_ENV
            and not is_live
            and get_setting(conn, "dev_mode_enabled", "1") == "1"
        )

        dev_debug_cycle = []
        if dev_mode_enabled:
            dev_debug_cycle = json.loads(get_setting(conn, "dev_debug_cycle_json", "[]"))

        return {
            "event_title": get_setting(conn, "event_title", "Julklappsspelet – Secret Santa"),
            "budget_info": get_setting(conn, "budget_info", "Ca 300 kr per julklapp"),
            "draw_generated": get_setting(conn, "draw_generated", "0") == "1",
            "is_live": is_live,
            "dev_mode_enabled": dev_mode_enabled,
            "participants": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "is_kid": bool(r["is_kid"]),
                    "wishlist": r["wishlist"],
                    "has_account": bool(r["has_account"]),
                }
                for r in users_rows
            ],
            "exclusions": exclusions,
            "aliases_pool": json.loads(get_setting(conn, "alias_pool_json", "[]")),
            "alias_cycle": json.loads(get_setting(conn, "alias_cycle_json", "[]")),
            "alias_board": alias_board,
            "kid_gifts": kid_gifts,
            "dev_debug_cycle": dev_debug_cycle,
        }
    finally:
        conn.close()


@app.post("/api/auth/login")
def login_user(req: LoginRequest):
    conn = get_connection()
    try:
        with conn:
            user, password_clean = _authenticate_user(conn, req.user_id, req.password)
            return _build_user_session_response(conn, user, password_clean)
    finally:
        conn.close()


@app.post("/api/user/draw-lot")
def user_draw_lot(req: LoginRequest):
    conn = get_connection()
    try:
        with conn:
            if get_setting(conn, "draw_generated", "0") != "1":
                raise HTTPException(
                    status_code=400,
                    detail="Lottningen är inte förberedd ännu! Be tomten/admin att aktivera lottningen först.",
                )
            user, password_clean = _authenticate_user(conn, req.user_id, req.password)
            if user["is_kid"]:
                raise HTTPException(
                    status_code=400,
                    detail="Barnen är med i Barnens Julklappshörna och behöver inte dra en vuxenlott.",
                )
            session_data = _build_user_session_response(conn, user, password_clean)
            if not session_data["assignment"]:
                raise HTTPException(status_code=400, detail="Ingen lott hittades för denna deltagare.")

            my_alias = session_data["assignment"]["my_alias"]
            conn.execute("UPDATE users SET has_drawn_lot = 1 WHERE id = ?", (user["id"],))
            conn.execute(
                "UPDATE alias_board SET has_drawn = 1 WHERE alias_name = ?",
                (my_alias,),
            )
            session_data["user"]["has_drawn_lot"] = True
            return session_data
    finally:
        conn.close()


@app.post("/api/user/wishlist")
def update_wishlist(req: WishlistUpdateRequest):
    conn = get_connection()
    try:
        with conn:
            user, _ = _authenticate_user(conn, req.user_id, req.password)
            conn.execute(
                "UPDATE users SET wishlist = ? WHERE id = ?",
                (req.wishlist.strip(), user["id"]),
            )
            return {"ok": True, "wishlist": req.wishlist.strip()}
    finally:
        conn.close()


@app.post("/api/user/kid-gift")
def create_kid_gift(req: KidGiftCreateRequest):
    conn = get_connection()
    try:
        with conn:
            user, password_clean = _authenticate_user(conn, req.user_id, req.password)
            recipient = conn.execute(
                "SELECT id, name, is_kid FROM users WHERE id = ?",
                (req.recipient_user_id,),
            ).fetchone()
            if not recipient:
                raise HTTPException(status_code=404, detail="Mottagaren hittades inte.")

            # Determine giver label without leaking identity unless chosen
            giver_label = "En hemlig tomte 🎅"
            if req.giver_mode == "name":
                giver_label = user["name"]
            elif req.giver_mode == "alias" and not user["is_kid"] and user["encrypted_assignment"]:
                decrypted = decrypt_payload(
                    user["encrypted_assignment"], password_clean, user["password_salt"]
                )
                giver_label = f"{decrypted['my_alias']} 🦌"

            server_salt = get_setting(conn, "server_salt")
            owner_tag = make_owner_tag(server_salt, user["id"])
            conn.execute(
                "INSERT INTO kid_gifts (recipient_user_id, giver_label, gift_note, owner_tag) VALUES (?, ?, ?, ?)",
                (recipient["id"], giver_label, req.gift_note.strip(), owner_tag),
            )
            return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/user/kid-gift/{gift_id}")
def delete_kid_gift(gift_id: int, user_id: int, password: str):
    conn = get_connection()
    try:
        with conn:
            user, _ = _authenticate_user(conn, user_id, password)
            server_salt = get_setting(conn, "server_salt")
            owner_tag = make_owner_tag(server_salt, user["id"])
            row = conn.execute(
                "SELECT owner_tag FROM kid_gifts WHERE id = ?", (gift_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Klapp-paxningen hittades inte.")
            if row["owner_tag"] != owner_tag:
                raise HTTPException(status_code=403, detail="Du kan bara ta bort dina egna paxade klappar.")
            conn.execute("DELETE FROM kid_gifts WHERE id = ?", (gift_id,))
            return {"ok": True}
    finally:
        conn.close()


# --- Admin / Pre-Live Seeding Endpoints ---

@app.post("/api/admin/settings")
def admin_update_settings(req: UpdateSettingsRequest):
    _check_admin(req.admin_password)
    conn = get_connection()
    try:
        with conn:
            _ensure_not_live(conn)
            set_setting(conn, "event_title", req.event_title.strip() or "Julklappsspelet – Secret Santa")
            set_setting(conn, "budget_info", req.budget_info.strip())
            cleaned_aliases = [a.strip() for a in req.aliases if a.strip()]
            set_setting(conn, "alias_pool_json", json.dumps(cleaned_aliases, ensure_ascii=False))
            return {"ok": True}
    finally:
        conn.close()


@app.post("/api/admin/participants")
def admin_add_participant(req: ParticipantCreateRequest):
    _check_admin(req.admin_password)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Namnet får inte vara tomt.")
    conn = get_connection()
    try:
        with conn:
            _ensure_not_live(conn)
            exists = conn.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone()
            if exists:
                raise HTTPException(status_code=400, detail="Det finns redan en deltagare med det namnet.")
            conn.execute(
                "INSERT INTO users (name, is_kid, wishlist, password_salt) VALUES (?, ?, ?, ?)",
                (name, 1 if req.is_kid else 0, req.wishlist.strip(), generate_salt()),
            )
            set_setting(conn, "draw_generated", "0")
            return {"ok": True}
    finally:
        conn.close()


@app.put("/api/admin/participants/{user_id}")
def admin_update_participant(user_id: int, req: ParticipantUpdateRequest):
    _check_admin(req.admin_password)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Namnet får inte vara tomt.")
    conn = get_connection()
    try:
        with conn:
            _ensure_not_live(conn)
            conflict = conn.execute(
                "SELECT 1 FROM users WHERE name = ? AND id != ?", (name, user_id)
            ).fetchone()
            if conflict:
                raise HTTPException(status_code=400, detail="En annan deltagare har redan det namnet.")
            conn.execute(
                "UPDATE users SET name = ?, is_kid = ?, wishlist = ? WHERE id = ?",
                (name, 1 if req.is_kid else 0, req.wishlist.strip(), user_id),
            )
            set_setting(conn, "draw_generated", "0")
            return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/admin/participants/{user_id}")
def admin_delete_participant(user_id: int, admin_password: str = ""):
    _check_admin(admin_password)
    conn = get_connection()
    try:
        with conn:
            _ensure_not_live(conn)
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            set_setting(conn, "draw_generated", "0")
            return {"ok": True}
    finally:
        conn.close()


@app.post("/api/admin/exclusions")
def admin_add_exclusion(req: ExclusionCreateRequest):
    _check_admin(req.admin_password)
    if req.user_a_id == req.user_b_id:
        raise HTTPException(status_code=400, detail="En person kan inte ha ett undantag med sig själv.")
    u1, u2 = min(req.user_a_id, req.user_b_id), max(req.user_a_id, req.user_b_id)
    conn = get_connection()
    try:
        with conn:
            _ensure_not_live(conn)
            exists = conn.execute(
                "SELECT 1 FROM exclusions WHERE user_a_id = ? AND user_b_id = ?",
                (u1, u2),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO exclusions (user_a_id, user_b_id) VALUES (?, ?)",
                    (u1, u2),
                )
            set_setting(conn, "draw_generated", "0")
            return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/admin/exclusions/{excl_id}")
def admin_delete_exclusion(excl_id: int, admin_password: str = ""):
    _check_admin(admin_password)
    conn = get_connection()
    try:
        with conn:
            _ensure_not_live(conn)
            conn.execute("DELETE FROM exclusions WHERE id = ?", (excl_id,))
            set_setting(conn, "draw_generated", "0")
            return {"ok": True}
    finally:
        conn.close()


@app.post("/api/admin/generate-draw")
def admin_generate_draw(req: GenerateDrawRequest):
    _check_admin(req.admin_password)
    conn = get_connection()
    try:
        with conn:
            _ensure_not_live(conn)
            try:
                result = _perform_draw_generation(
                    conn,
                    seed=req.seed,
                    custom_cycle_user_ids=req.custom_cycle_user_ids,
                )
            except MatchingError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"ok": True, **result}
    finally:
        conn.close()


@app.post("/api/admin/go-live")
def admin_go_live(req: AdminAuthMixin):
    _check_admin(req.admin_password)
    conn = get_connection()
    try:
        with conn:
            if get_setting(conn, "draw_generated", "0") != "1":
                try:
                    _perform_draw_generation(conn)
                except MatchingError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            # Wipe any developer debug mapping so admin cannot inspect who has who!
            set_setting(conn, "dev_debug_cycle_json", "[]")
            set_setting(conn, "dev_mode_enabled", "0")
            set_setting(conn, "is_live", "1")
            return {"ok": True}
    finally:
        conn.close()


@app.post("/api/admin/save-seed")
def admin_save_seed(req: AdminAuthMixin):
    _check_admin(req.admin_password)
    conn = get_connection()
    try:
        seed_dict = export_current_to_seed_dict(conn)
        SEED_PATH.write_text(
            json.dumps(seed_dict, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/admin/reset-from-seed")
def admin_reset_from_seed(req: AdminAuthMixin):
    _check_admin(req.admin_password)
    conn = get_connection()
    try:
        with conn:
            load_seed_into_db(conn, SEED_PATH)
            return {"ok": True}
    finally:
        conn.close()
