"""
NetLine — a real-time, multi-room client-server chat application.

Architecture
------------
This is a genuine client-server design, not a polling workaround:

    Browser  <--WebSocket-->  Flask-SocketIO server  <-->  SQLite

Flask-SocketIO keeps one persistent, bidirectional connection per
connected browser tab (a "client"). The server holds all shared state
in memory (who is online, who is typing) and durable state on disk
(message history), and pushes updates to every relevant client the
moment something happens — no client ever has to ask "anything new?"

Run locally:
    pip install -r requirements.txt
    python app.py
    # open http://localhost:5000

Deploy: see README.md (Render / Railway / Fly.io / Docker instructions,
all using the included Procfile / render.yaml / Dockerfile).
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DB_PATH = Path(os.environ.get("CHAT_DB_PATH", BASE_DIR / "chat.db"))
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DEFAULT_ROOMS = ["general", "random", "help"]
HISTORY_LIMIT = 100
MAX_MESSAGE_LEN = 2000
MAX_USERNAME_LEN = 24
TYPING_TIMEOUT_S = 4  # client-side hint only; server just relays events

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# "threading" mode needs no monkey-patching library (eventlet/gevent),
# so it has no Python-version compatibility risk and works unchanged
# on any host. It's plenty for a chat app's concurrency needs; see
# README.md if you later want to swap in eventlet/gevent for very
# high connection counts.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# --------------------------------------------------------------------------
# Storage layer (SQLite — swap for Postgres by editing this module only)
# --------------------------------------------------------------------------


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                room       TEXT NOT NULL,
                username   TEXT NOT NULL,
                body       TEXT NOT NULL,
                kind       TEXT NOT NULL DEFAULT 'message',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room, id)"
        )


def save_message(room: str, username: str, body: str, kind: str = "message") -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (room, username, body, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (room, username, body, kind, created_at),
        )
        msg_id = cur.lastrowid
    return {
        "id": msg_id,
        "room": room,
        "username": username,
        "body": body,
        "kind": kind,
        "created_at": created_at,
    }


def load_history(room: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, room, username, body, kind, created_at FROM messages "
            "WHERE room = ? ORDER BY id DESC LIMIT ?",
            (room, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


# --------------------------------------------------------------------------
# In-memory presence (per-process; fine for a single web worker — see
# README for notes on scaling to multiple workers with a message queue)
# --------------------------------------------------------------------------

# sid -> {"username": str, "room": str}
clients: dict[str, dict] = {}
# room -> set of usernames currently marked as typing
typing_in_room: dict[str, set] = {}


def room_roster(room: str) -> list[str]:
    names = {c["username"] for c in clients.values() if c["room"] == room}
    return sorted(names)


def sanitize(text: str, max_len: int) -> str:
    return text.strip()[:max_len]


# --------------------------------------------------------------------------
# HTTP routes
# --------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html", rooms=DEFAULT_ROOMS)


@app.route("/healthz")
def healthz():
    return {"status": "ok", "clients_connected": len(clients)}


# --------------------------------------------------------------------------
# Socket.IO events — this is the "server" half of the client-server pair
# --------------------------------------------------------------------------


@socketio.on("connect")
def on_connect():
    # Nothing joins a room yet; the client sends "join" once it has a
    # username, so a bare connection doesn't appear in any roster.
    emit("connected", {"sid": request.sid})


@socketio.on("join")
def on_join(data):
    username = sanitize(str(data.get("username", "")), MAX_USERNAME_LEN)
    room = sanitize(str(data.get("room", "general")), 40) or "general"

    if not username:
        emit("join_error", {"message": "Choose a display name first."})
        return

    if any(
        c["username"].lower() == username.lower() and c["room"] == room
        for c in clients.values()
    ):
        emit("join_error", {"message": f'"{username}" is already taken in #{room}.'})
        return

    clients[request.sid] = {"username": username, "room": room}
    join_room(room)

    emit("history", {"room": room, "messages": load_history(room)})
    emit("roster", {"room": room, "users": room_roster(room)}, to=room)

    system_msg = save_message(room, "system", f"{username} joined #{room}", kind="system")
    emit("message", system_msg, to=room)


@socketio.on("send_message")
def on_send_message(data):
    client = clients.get(request.sid)
    if not client:
        emit("join_error", {"message": "You've been disconnected — rejoin to send messages."})
        return

    body = sanitize(str(data.get("body", "")), MAX_MESSAGE_LEN)
    if not body:
        return

    msg = save_message(client["room"], client["username"], body)
    emit("message", msg, to=client["room"])

    typing_in_room.get(client["room"], set()).discard(client["username"])
    emit(
        "typing",
        {"room": client["room"], "users": sorted(typing_in_room.get(client["room"], set()))},
        to=client["room"],
    )


@socketio.on("typing")
def on_typing(data):
    client = clients.get(request.sid)
    if not client:
        return
    room = client["room"]
    typing_in_room.setdefault(room, set())
    if data.get("is_typing"):
        typing_in_room[room].add(client["username"])
    else:
        typing_in_room[room].discard(client["username"])
    emit("typing", {"room": room, "users": sorted(typing_in_room[room])}, to=room)


@socketio.on("switch_room")
def on_switch_room(data):
    client = clients.get(request.sid)
    if not client:
        return

    old_room = client["room"]
    new_room = sanitize(str(data.get("room", "general")), 40) or "general"
    if new_room == old_room:
        return

    leave_room(old_room)
    typing_in_room.get(old_room, set()).discard(client["username"])
    emit("roster", {"room": old_room, "users": room_roster(old_room)}, to=old_room)

    client["room"] = new_room
    join_room(new_room)
    emit("history", {"room": new_room, "messages": load_history(new_room)})
    emit("roster", {"room": new_room, "users": room_roster(new_room)}, to=new_room)


@socketio.on("disconnect")
def on_disconnect():
    client = clients.pop(request.sid, None)
    if not client:
        return
    room, username = client["room"], client["username"]
    typing_in_room.get(room, set()).discard(username)

    emit("roster", {"room": room, "users": room_roster(room)}, to=room)
    emit("typing", {"room": room, "users": sorted(typing_in_room.get(room, set()))}, to=room)
    system_msg = save_message(room, "system", f"{username} left #{room}", kind="system")
    emit("message", system_msg, to=room)


# --------------------------------------------------------------------------

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    # Flask-SocketIO refuses to start Werkzeug's bundled dev server outside
    # local/debug use unless this is set explicitly. For gunicorn-based
    # deploys (Procfile/Dockerfile) this line never runs at all — it only
    # matters for hosts, like Streamlit Cloud, that execute app.py directly
    # instead of going through gunicorn. Fine for a small chat app; swap in
    # a production WSGI server (see Procfile) if traffic grows.
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=True)
