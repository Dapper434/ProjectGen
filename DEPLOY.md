# Deploying FactoryOS

Frontend on Vercel, backend on your own server behind Tailscale Funnel.

```
Browser ──► Vercel (static frontend + /api/* rewrite)
                        │
                        ▼
             https://<machine>.<tailnet>.ts.net   (Tailscale Funnel, public HTTPS)
                        │
                        ▼
             gunicorn/Flask on 127.0.0.1:5000  +  factoryos.db (SQLite)
                        ▲
Fathom webhooks ────────┘  (hit the funnel URL directly)
```

The browser only ever talks to the Vercel domain — the `/api/*` rewrite in
`frontend/vercel.json` proxies to the funnel, so session cookies stay
first-party and no CORS/SameSite=None configuration is needed. In local dev the
Vite proxy (`frontend/vite.config.js`) plays the same role.

## 1. Server: backend

```bash
# System deps (Debian/Ubuntu) — WeasyPrint needs the Pango/Cairo stack
sudo apt install python3-venv libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev

git clone <repo> && cd ProjectGen/backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

`backend/.env` on the server:

```
SECRET_KEY=<long random string — python3 -c "import secrets; print(secrets.token_hex(32))">
PRODUCTION=1                    # turns on Secure session cookies
NIM_API_KEY=...
NIM_MODEL=nvidia/nemotron-3-super-120b-a12b
FATHOM_API_KEY=...
FATHOM_WEBHOOK_SECRET=...       # from step 3 — re-register against the funnel URL
DATABASE_URL=sqlite:///factoryos.db
```

Initialize and run:

```bash
venv/bin/python migrate_schema.py        # creates/upgrades factoryos.db (or copy your existing one up)
venv/bin/gunicorn --workers 1 --threads 8 --bind 127.0.0.1:5000 wsgi:app
```

One worker on purpose: agent jobs run in an in-process thread pool and SQLite
has a single writer. Keep it alive with systemd — `/etc/systemd/system/factoryos.service`:

```ini
[Unit]
Description=FactoryOS backend
After=network.target

[Service]
User=<you>
WorkingDirectory=/home/<you>/ProjectGen/backend
ExecStart=/home/<you>/ProjectGen/backend/venv/bin/gunicorn --workers 1 --threads 8 --bind 127.0.0.1:5000 wsgi:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now factoryos
```

## 2. Server: Tailscale Funnel

```bash
sudo tailscale funnel --bg 5000
tailscale funnel status     # shows your public URL: https://<machine>.<tailnet>.ts.net
```

First time only: the admin console will prompt you to enable HTTPS certificates
and add the `funnel` node attribute to your tailnet policy (the command prints
the link). The URL is stable across reboots — register it once, it keeps working.

Sanity check from any network: `curl https://<machine>.<tailnet>.ts.net/api/engagements`

## 3. Fathom webhook

The webhook must point at the funnel URL (a webhook created against localhost or
a placeholder never delivers). Each webhook has its own secret, so re-register:

```bash
venv/bin/python fathom.py register https://<machine>.<tailnet>.ts.net/api/webhooks/fathom
```

Put the printed secret in `.env` as `FATHOM_WEBHOOK_SECRET` (replacing the old
one) and `sudo systemctl restart factoryos`. Delete the stale webhook in Fathom
Settings → API Access if one exists.

## 4. Vercel: frontend

1. Edit `frontend/vercel.json` — replace the rewrite destination with your real
   funnel URL.
2. Import the repo in Vercel with **Root Directory = `frontend`** (framework
   preset: Vite). No env vars needed — the API base is the relative `/api`.
3. Deploy. The second rewrite in `vercel.json` is the SPA fallback so deep links
   like `/engagements/5` load index.html.

## Checklist

- [ ] `curl https://<funnel-url>/api/engagements` returns JSON from anywhere
- [ ] Log in on the Vercel URL (cookie should stick — check a second page load)
- [ ] `POST /api/webhooks/fathom` unsigned returns 401 (secret active)
- [ ] Record a short Zoom call with Fathom → appears in `/inbox` (≈a few min after the call ends)
- [ ] PDF download works through the proxy (Brief → Download PDF)

## Notes

- Funnel bandwidth is rate-limited by Tailscale — fine for this app's JSON and
  the occasional PDF, not for heavy media.
- SQLite is single-writer: keep `--workers 1`. If the app outgrows that, move
  `DATABASE_URL` to Postgres before adding workers.
- The Flask dev server (`python app.py`) is for local dev only; production is
  gunicorn via `wsgi.py`.
