#!/bin/bash
# {TITLE} — opens the reading edition in Chrome from http://localhost:{PORT}.
# Served this way (not as a file), the page lets Chrome remember "Always allow localhost:{PORT} to open zotero links".
# Closing this window stops the local server.
cd "$(dirname "$0")" || exit 1
PORT={PORT}
listening() { /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; }
if ! listening; then
  /usr/bin/python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
  SERVER=$!
  for _ in 1 2 3 4 5 6 7 8 9 10; do listening && break; sleep 0.3; done
fi
open -a "Google Chrome" "http://localhost:$PORT/index.html"
if [ -n "$SERVER" ]; then
  echo "The review is served on http://localhost:$PORT — keep this window open while you read."
  wait "$SERVER"
fi
