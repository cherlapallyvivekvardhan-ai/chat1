# NetLine — real-time client-server chat

A genuine client-server chat application: a Flask + Socket.IO server holds
shared state (message history, who's online, who's typing) and pushes
updates to every connected browser over a persistent WebSocket connection.
No polling, no page reloads.

```
Browser tab (client)  <==WebSocket==>  Flask-SocketIO (server)  <-->  SQLite
Browser tab (client)  <==WebSocket==>          ^
Browser tab (client)  <==WebSocket==>          |
                                        one shared process,
                                        broadcasts to every
                                        client in a room
```

## Features

- **Real-time messaging** over WebSockets (Socket.IO), with an automatic
  fallback to long-polling if a network blocks WebSocket upgrades.
- **Multiple rooms** (`general`, `random`, `help` by default — add more by
  editing `DEFAULT_ROOMS` in `app.py`).
- **Presence** — a live roster of who's online in your current room.
- **Typing indicators.**
- **Persistent history** in SQLite; the last 100 messages in a room load
  when you join it, so refreshing or reconnecting doesn't lose context.
- **System messages** for joins/leaves.
- **No build step** — plain HTML/CSS/JS on the client, so there's nothing
  to compile before deploying.

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000** in a couple of different browser
tabs (or browsers) to see messages, presence, and typing indicators sync
between them in real time.

## Project layout

```
chat-app/
├── app.py                 # Flask app + Socket.IO event handlers + SQLite storage
├── templates/index.html   # Join screen + chat UI (server-rendered shell)
├── static/css/style.css   # Styling
├── static/js/main.js      # Socket.IO client logic
├── requirements.txt
├── Procfile               # gunicorn + eventlet, for Render/Railway/Heroku-style hosts
├── render.yaml            # One-click Render.com blueprint (with a persistent disk)
├── Dockerfile             # For Fly.io or any container host
├── .env.example
└── .gitignore
```

## Deploying

### Push to GitHub first

```bash
git init
git add .
git commit -m "Initial commit: NetLine chat app"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### Option A — Render.com (easiest)

1. Push this repo to GitHub.
2. In Render, choose **New → Blueprint**, point it at the repo — it will
   read `render.yaml` and configure the web service, the persistent disk
   for `chat.db`, and a generated `SECRET_KEY` automatically.
3. Deploy. Render gives you a public URL immediately.

### Option B — Railway

1. Push to GitHub, then **New Project → Deploy from GitHub repo** in Railway.
2. Railway detects the `Procfile` automatically. Add a volume if you want
   chat history to persist across deploys, and mount it at the path you
   set for `CHAT_DB_PATH`.
3. Set the `SECRET_KEY` environment variable in the Railway dashboard.

### Option C — Fly.io (Docker)

```bash
fly launch          # detects the Dockerfile, asks a few questions
fly volumes create chat_data --size 1
# then set CHAT_DB_PATH=/data/chat.db and mount the volume at /data
# in the generated fly.toml
fly deploy
```

### Option D — any Docker host

```bash
docker build -t netline-chat .
docker run -p 8000:8000 -e SECRET_KEY=$(openssl rand -hex 32) netline-chat
```

## A note on Streamlit Community Cloud

This is a **Flask + Socket.IO** app, not a Streamlit app, and Streamlit
Community Cloud only knows how to run and route traffic to Streamlit
scripts (`streamlit run app.py`) — it can't proxy WebSocket connections to
a separate Flask server or serve its routes. It won't work as a host for
this project even once it imports cleanly. Use one of the options above
(Render, Railway, Fly.io, or plain Docker) instead — all of them run this
app.py's Flask/Socket.IO server directly, which is what it needs.

## Scaling beyond one process

The server runs in Socket.IO's `"threading"` async mode, which needs no
monkey-patching library (no `eventlet`/`gevent`) and so has no
Python-version compatibility risk — it's what avoids the crash some
hosts hit when `eventlet` doesn't yet support their Python version. It
keeps presence and typing state in memory in a single worker (`-w 1` in
the Procfile), which is correct and simple for one process, and is
plenty of concurrency for a chat app at moderate scale. If you outgrow a
single instance:

- Swap SQLite for Postgres (only `app.py`'s storage functions need to change).
- Run Socket.IO with a **message queue backend** (Redis is the standard
  choice: `socketio = SocketIO(app, message_queue="redis://...")` on every
  worker) so broadcasts reach clients connected to *other* processes.
- Move the in-memory `clients` / `typing_in_room` dictionaries into Redis
  as well, since each worker currently only knows about its own clients.
- At that point `eventlet` or `gevent` (with their matching gunicorn
  worker class) can raise the per-process connection ceiling — reintroduce
  one only if profiling shows `threading` mode is the bottleneck.

## Configuration

All configuration is environment variables — see `.env.example`:

| Variable      | Purpose                                   | Default    |
|---------------|--------------------------------------------|-----------|
| `SECRET_KEY`  | Signs Flask's session cookie               | dev value — **change in production** |
| `CHAT_DB_PATH`| Path to the SQLite file                    | `chat.db` in the project directory |
| `PORT`        | Port the dev server binds to               | `5000`     |

## License

MIT — do whatever you like with it.
