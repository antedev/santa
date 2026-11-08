import hashlib
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
    generate_invite_token,
    get_connection,
    get_setting,
    init_db,
    load_seed_into_db,
    set_setting,
)
from app.matcher import MatchingError, assign_aliases, find_single_cycle


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    conn = get_connection()
    try:
        with conn:
            if get_setting(conn, "draw_generated", "0") == "0":
                try:
                    _perform_draw_generation(conn)
                except MatchingError:
                    pass
    finally:
        conn.close()
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
    invite_token: Optional[str] = None
    reset_pin: bool = False


class WishlistUpdateRequest(BaseModel):
    user_id: int
    password: str
    wishlist: str


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
    all_users = conn.execute(
        "SELECT id, name, is_kid FROM users ORDER BY id ASC"
    ).fetchall()
    adults = [r for r in all_users if not r["is_kid"]]
    kids = [r for r in all_users if r["is_kid"]]

    adult_ids = [r["id"] for r in adults]
    all_ids = [r["id"] for r in all_users]
    id_to_name = {r["id"]: r["name"] for r in all_users}

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
    user_aliases = assign_aliases(all_ids, aliases_pool, seed=seed)

    # Rotate server_salt so preclaim keys are fresh
    server_salt = generate_salt()
    set_setting(conn, "server_salt", server_salt)

    # Reset passwords and draw status so pre-claim encryption is consistent
    for uid in all_ids:
        conn.execute(
            "UPDATE users SET password_hash = NULL, password_salt = ?, is_password_encrypted = 0, has_drawn_lot = 0 WHERE id = ?",
            (generate_salt(), uid),
        )

    n = len(cycle_ids)
    alias_cycle: List[str] = []
    dev_debug_cycle: List[Dict[str, Any]] = []

    # 1. Encrypt adult main loop assignments
    for i in range(n):
        giver_id = cycle_ids[i]
        target_id = cycle_ids[(i + 1) % n]
        giver_alias = user_aliases[giver_id]
        target_alias = user_aliases[target_id]
        alias_cycle.append(giver_alias)

        user_row = conn.execute(
            "SELECT password_salt, invite_token FROM users WHERE id = ?", (giver_id,)
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
        token_ciphertext = encrypt_payload(
            payload, user_row["invite_token"], user_row["password_salt"]
        )
        conn.execute(
            "UPDATE users SET encrypted_assignment = ?, token_encrypted_assignment = ?, is_password_encrypted = 0, has_drawn_lot = 0 WHERE id = ?",
            (ciphertext, token_ciphertext, giver_id),
        )

        dev_debug_cycle.append(
            {
                "giver_id": giver_id,
                "giver_name": id_to_name[giver_id],
                "giver_alias": giver_alias,
                "target_id": target_id,
                "target_name": id_to_name[target_id],
                "target_alias": target_alias,
                "is_kid_bonus": False,
            }
        )

    # 2. Encrypt optional bonus lottery assignments for kids (outside the main loop!)
    rng = random.Random()
    if seed is not None and str(seed).strip() != "":
        seed_bytes = hashlib.sha256(("kids:" + str(seed).strip()).encode("utf-8")).digest()
        rng.seed(int.from_bytes(seed_bytes, "big"))
    else:
        rng.seed()

    for kid in kids:
        kid_id = kid["id"]
        possible_targets = [uid for uid in adult_ids if uid != kid_id]
        if not possible_targets:
            continue
        target_id = rng.choice(possible_targets)
        kid_alias = user_aliases[kid_id]
        target_alias = user_aliases[target_id]

        user_row = conn.execute(
            "SELECT password_salt, invite_token FROM users WHERE id = ?", (kid_id,)
        ).fetchone()
        payload = {
            "target_id": target_id,
            "target_name": id_to_name[target_id],
            "my_alias": kid_alias,
            "target_alias": target_alias,
        }
        ciphertext = encrypt_preclaim_assignment(
            payload, server_salt, kid_id, user_row["password_salt"]
        )
        token_ciphertext = encrypt_payload(
            payload, user_row["invite_token"], user_row["password_salt"]
        )
        conn.execute(
            "UPDATE users SET encrypted_assignment = ?, token_encrypted_assignment = ?, is_password_encrypted = 0, has_drawn_lot = 0 WHERE id = ?",
            (ciphertext, token_ciphertext, kid_id),
        )

        dev_debug_cycle.append(
            {
                "giver_id": kid_id,
                "giver_name": id_to_name[kid_id],
                "giver_alias": kid_alias,
                "target_id": target_id,
                "target_name": id_to_name[target_id],
                "target_alias": target_alias,
                "is_kid_bonus": True,
            }
        )

    # Populate alias_board for the adult main loop in shuffled order
    conn.execute("DELETE FROM alias_board")
    shuffled_aliases = list(alias_cycle)
    random.shuffle(shuffled_aliases)
    for alias in shuffled_aliases:
        conn.execute(
            "INSERT INTO alias_board (alias_name, has_drawn, is_kid_bonus) VALUES (?, 0, 0)",
            (alias,),
        )

    set_setting(conn, "alias_cycle_json", json.dumps(alias_cycle, ensure_ascii=False))
    set_setting(conn, "draw_generated", "1")
    conn.execute("DELETE FROM settings WHERE key = 'dev_debug_cycle_json'")

    return {
        "alias_cycle": alias_cycle,
        "adult_count": n,
    }


def _authenticate_user(
    conn,
    user_id: int,
    password: str,
    invite_token: Optional[str] = None,
    reset_pin: bool = False,
):
    password_clean = password.strip()
    if len(password_clean) < 2:
        raise HTTPException(status_code=400, detail="PIN-koden måste vara minst 2 tecken.")

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Deltagaren hittades inte.")

    server_salt = get_setting(conn, "server_salt")

    if user["password_hash"] is None or reset_pin:
        # First-time registration OR resetting PIN via personal link
        if not invite_token or invite_token.strip() != user["invite_token"]:
            raise HTTPException(
                status_code=403,
                detail="Använd din personliga länk för att välja eller återställa din PIN-kod.",
            )
        pw_hash = hash_password(password_clean, user["password_salt"])
        plain_payload = None
        if user["token_encrypted_assignment"]:
            plain_payload = decrypt_payload(
                user["token_encrypted_assignment"],
                user["invite_token"],
                user["password_salt"],
            )
        elif user["encrypted_assignment"] and not user["is_password_encrypted"]:
            plain_payload = decrypt_preclaim_assignment(
                user["encrypted_assignment"],
                server_salt,
                user["id"],
                user["password_salt"],
            )

        if plain_payload is not None:
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
            raise HTTPException(status_code=401, detail="Fel PIN-kod! Försök igen.")
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
    if user["encrypted_assignment"]:
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

    return {
        "user": {
            "id": user["id"],
            "name": user["name"],
            "is_kid": bool(user["is_kid"]),
            "wishlist": user["wishlist"],
            "has_drawn_lot": bool(user["has_drawn_lot"]),
        },
        "assignment": assignment,
    }


# --- Routes ---

@app.get("/")
@app.get("/admin")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/invite/{invite_token}")
def get_invite_info(invite_token: str):
    conn = get_connection()
    try:
        user = conn.execute(
            "SELECT id, name, is_kid, password_hash IS NOT NULL AS has_account FROM users WHERE invite_token = ?",
            (invite_token.strip(),),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Ogiltig eller utgången personlig länk.")
        return {
            "id": user["id"],
            "name": user["name"],
            "is_kid": bool(user["is_kid"]),
            "has_account": bool(user["has_account"]),
            "invite_token": invite_token.strip(),
        }
    finally:
        conn.close()


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
            "SELECT alias_name, has_drawn, is_kid_bonus FROM alias_board ORDER BY is_kid_bonus ASC, alias_name COLLATE NOCASE ASC"
        ).fetchall()
        alias_board = [
            {
                "alias_name": r["alias_name"],
                "has_drawn": bool(r["has_drawn"]),
                "is_kid_bonus": bool(r["is_kid_bonus"]),
            }
            for r in alias_board_rows
        ]

        is_live = get_setting(conn, "is_live", "0") == "1"

        return {
            "event_title": get_setting(conn, "event_title", "Julklappsspelet"),
            "budget_info": get_setting(conn, "budget_info", "Secret Santa för familjen"),
            "draw_generated": get_setting(conn, "draw_generated", "0") == "1",
            "is_live": is_live,
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
        }
    finally:
        conn.close()


@app.post("/api/auth/login")
def login_user(req: LoginRequest):
    conn = get_connection()
    try:
        with conn:
            user, password_clean = _authenticate_user(
                conn, req.user_id, req.password, req.invite_token, req.reset_pin
            )
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
                    detail="Lottningen är inte förberedd ännu!",
                )
            user, password_clean = _authenticate_user(
                conn, req.user_id, req.password, req.invite_token
            )
            session_data = _build_user_session_response(conn, user, password_clean)
            if not session_data["assignment"]:
                raise HTTPException(status_code=400, detail="Ingen lott hittades för denna deltagare.")

            my_alias = session_data["assignment"]["my_alias"]
            conn.execute("UPDATE users SET has_drawn_lot = 1 WHERE id = ?", (user["id"],))
            if user["is_kid"]:
                # Add kid's bonus alias to alias_board once they actually choose to draw!
                conn.execute(
                    "INSERT INTO alias_board (alias_name, has_drawn, is_kid_bonus) VALUES (?, 1, 1) "
                    "ON CONFLICT(alias_name) DO UPDATE SET has_drawn = 1",
                    (my_alias,),
                )
            else:
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


# --- Admin Endpoints ---

@app.post("/api/admin/invites")
def admin_get_invites(req: AdminAuthMixin):
    _check_admin(req.admin_password)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, is_kid, invite_token, password_hash IS NOT NULL AS has_account "
            "FROM users ORDER BY is_kid ASC, name COLLATE NOCASE ASC"
        ).fetchall()
        return {
            "invites": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "is_kid": bool(r["is_kid"]),
                    "invite_token": r["invite_token"],
                    "has_account": bool(r["has_account"]),
                }
                for r in rows
            ]
        }
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
                "INSERT INTO users (name, is_kid, wishlist, invite_token, password_salt) VALUES (?, ?, ?, ?, ?)",
                (name, 1 if req.is_kid else 0, req.wishlist.strip(), generate_invite_token(), generate_salt()),
            )
            _perform_draw_generation(conn)
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
            _perform_draw_generation(conn)
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
            try:
                _perform_draw_generation(conn)
            except MatchingError:
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
            _perform_draw_generation(conn)
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
            _perform_draw_generation(conn)
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
            try:
                _perform_draw_generation(conn)
            except MatchingError:
                pass
            return {"ok": True}
    finally:
        conn.close()
