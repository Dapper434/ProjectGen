# Deploying FactoryOS

Frontend on Vercel, backend on your own server behind a Cloudflare Tunnel.

```
Browser ──► Vercel (static frontend + /api/* rewrite)
                        │
                        ▼
             https://<random>.trycloudflare.com   (Cloudflare Tunnel, public HTTPS)
                        │
                        ▼
             gunicorn/Flask on 127.0.0.1:5000  +  factoryos.db (SQLite)
                        ▲
Fathom webhooks ────────┘  (hit the tunnel URL directly)
```

The browser only ever talks to the Vercel domain — the `/api/*` rewrite in
`frontend/vercel.json` proxies to the tunnel, so session cookies stay
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
FATHOM_WEBHOOK_SECRET=...       # from step 3 — re-register against the tunnel URL
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

## 2. Server: Cloudflare Tunnel

No domain is required for this — a **Quick Tunnel** gets you a public HTTPS
URL immediately, at the cost of that URL changing every time `cloudflared`
restarts (see "Making the hostname permanent" below for the fix once you have
a domain).

```bash
# Install cloudflared (Debian/Ubuntu)
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Quick tunnel — no domain or Cloudflare login needed, prints a random
# https://<random>.trycloudflare.com URL that proxies to the backend
cloudflared tunnel --url http://127.0.0.1:5000
```

Keep it alive with systemd — `/etc/systemd/system/cloudflared.service`:

```ini
[Unit]
Description=Cloudflare Tunnel for FactoryOS
After=network.target factoryos.service

[Service]
User=<you>
ExecStart=/usr/local/bin/cloudflared tunnel --url http://127.0.0.1:5000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now cloudflared
```

**The hostname changes every time this process (re)starts** — crash, reboot,
`systemctl restart`, all of it. Get the current URL after each start with:

```bash
sudo journalctl -u cloudflared -f | grep trycloudflare.com
```

Whenever it changes, redo step 4 (update `vercel.json`, redeploy) and step 3
(re-register the Fathom webhook) below.

Sanity check from any network: `curl https://<random>.trycloudflare.com/api/engagements`

**Making the hostname permanent:** once you have any domain added to your
Cloudflare account, switch to a named tunnel for a stable hostname that
survives restarts:

```bash
cloudflared tunnel login
cloudflared tunnel create factoryos
cloudflared tunnel route dns factoryos api.yourdomain.com
cloudflared tunnel run factoryos   # use this instead of `--url` in the systemd unit
```

Not required to get started — just the natural next step once you own a domain.

## 3. Fathom webhook

The webhook must point at the current tunnel URL (a webhook created against
localhost or a placeholder never delivers). Each webhook has its own secret,
so re-register whenever the tunnel URL changes:

```bash
venv/bin/python fathom.py register https://<random>.trycloudflare.com/api/webhooks/fathom
```

Put the printed secret in `.env` as `FATHOM_WEBHOOK_SECRET` (replacing the old
one) and `sudo systemctl restart factoryos`. Delete the stale webhook in Fathom
Settings → API Access if one exists.

## 4. Vercel: frontend

1. Edit `frontend/vercel.json` — replace the rewrite destination
   (`REPLACE-WITH-CLOUDFLARE-TUNNEL-URL.trycloudflare.com`) with your real
   tunnel URL.
2. Import the repo in Vercel with **Root Directory = `frontend`** (framework
   preset: Vite). No env vars needed — the API base is the relative `/api`.
3. Deploy. The second rewrite in `vercel.json` is the SPA fallback so deep links
   like `/engagements/5` load index.html.

## Checklist

- [ ] `curl https://<tunnel-url>/api/engagements` returns JSON from anywhere
- [ ] Log in on the Vercel URL (cookie should stick — check a second page load)
- [ ] `POST /api/webhooks/fathom` unsigned returns 401 (secret active)
- [ ] Record a short Zoom call with Fathom → appears in `/inbox` (≈a few min after the call ends)
- [ ] PDF download works through the proxy (Brief → Download PDF)

## Notes

- Quick Tunnels have no uptime/SLA guarantee and hand out a new hostname on
  every restart — fine for a hackathon/demo, but every restart means updating
  `vercel.json` (redeploy) and re-registering the Fathom webhook. Buy any cheap
  domain and switch to a named tunnel (see above) once you want this to stop.
- SQLite is single-writer: keep `--workers 1`. If the app outgrows that, move
  `DATABASE_URL` to Postgres before adding workers.
- The Flask dev server (`python app.py`) is for local dev only; production is
  gunicorn via `wsgi.py`.
