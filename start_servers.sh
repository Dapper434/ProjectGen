#!/bin/bash
# FactoryOS — one-command dev startup.
# Starts backend (Flask :5000) + frontend (Vite :5173), health-checks both,
# streams both logs live to this terminal, and stays attached in the
# foreground until Ctrl+C (which stops both servers). Safe to re-run: it
# kills whatever previously held the ports first (re-running instead of
# starting a second copy avoids orphaned duplicate Vite processes that lose
# the port race and just burn memory).

set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_LOG=/tmp/backend_run.log
FRONTEND_LOG=/tmp/frontend_run.log

# --- stop anything already on our ports ---
fuser -k 5000/tcp 2>/dev/null
fuser -k 5173/tcp 2>/dev/null
sleep 1

# --- backend ---
cd "$ROOT/backend"
if [ ! -d venv ]; then
  echo "ERROR: backend/venv missing. Run: python3 -m venv venv && venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
# .env (NIM_API_KEY etc.) is auto-loaded by app.py via python-dotenv.
source venv/bin/activate
# --with-threads is Flask's default, but pinned explicitly here: agent calls run in a
# background thread pool (see app.py) and the frontend polls for completion, so the
# dev server must actually serve those polling requests concurrently.
python3 -m flask run --port=5000 --with-threads > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# --- frontend ---
cd "$ROOT/frontend"
npx vite --port 5173 --host 0.0.0.0 > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# --- stream both logs to this terminal, prefixed so they're distinguishable ---
tail -n +1 -F "$BACKEND_LOG" 2>/dev/null | sed -u 's/^/[backend]  /' &
TAIL_BACKEND_PID=$!
tail -n +1 -F "$FRONTEND_LOG" 2>/dev/null | sed -u 's/^/[frontend] /' &
TAIL_FRONTEND_PID=$!

CLEANED_UP=0
cleanup() {
  [ "$CLEANED_UP" = "1" ] && return
  CLEANED_UP=1
  echo ""
  echo "Shutting down..."
  # `npx vite` forks an actual node child that outlives killing the npx wrapper
  # PID, so stop both servers by port (same mechanism as the startup cleanup)
  # rather than by the PIDs $! captured.
  fuser -k 5000/tcp 2>/dev/null
  fuser -k 5173/tcp 2>/dev/null
  kill "$TAIL_BACKEND_PID" "$TAIL_FRONTEND_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# --- health checks: poll, don't guess ---
wait_for() { # url name log
  for _ in $(seq 1 30); do
    if curl -sf -o /dev/null --connect-timeout 2 "$1"; then
      echo "$2 is up ✓"
      return 0
    fi
    sleep 1
  done
  echo "$2 FAILED to start — last log lines:" >&2
  tail -15 "$3" >&2
  return 1
}

OK=0
wait_for http://localhost:5000/api/engagements "Backend (:5000)" "$BACKEND_LOG" || OK=1
wait_for http://localhost:5173/ "Frontend (:5173)" "$FRONTEND_LOG" || OK=1

echo "---"
echo "App:      http://localhost:5173  (producer/demo or am/demo)"
echo "API:      http://localhost:5000"
echo "Logs:     streaming below, and written to $BACKEND_LOG · $FRONTEND_LOG"
if ! grep -q '^NIM_API_KEY=.\+' "$ROOT/backend/.env" 2>/dev/null; then
  echo "NOTE:     NIM_API_KEY is empty in backend/.env — agents will emit placeholder content."
fi

if [ "$OK" -ne 0 ]; then
  exit $OK
fi

echo "Press Ctrl+C to stop both servers."
echo "---"
wait "$BACKEND_PID" "$FRONTEND_PID"
