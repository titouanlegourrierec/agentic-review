#!/bin/sh
# {TITLE} — serves the reading edition on http://localhost:{PORT} and opens it (Linux).
# Keep this terminal open while you read; Ctrl+C stops the server.
cd "$(dirname "$0")" || exit 1
PORT={PORT}
python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
SERVER=$!
sleep 1
xdg-open "http://localhost:$PORT/index.html" >/dev/null 2>&1 || echo "Open http://localhost:$PORT/index.html in Chrome."
echo "The review is served on http://localhost:$PORT — press Ctrl+C to stop."
wait "$SERVER"
