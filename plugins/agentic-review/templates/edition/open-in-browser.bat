@echo off
rem {TITLE} - serves the reading edition on http://localhost:{PORT} and opens it (Windows).
rem Keep this window open while you read; closing it stops the server.
cd /d "%~dp0"
start "" "http://localhost:{PORT}/index.html"
python -m http.server {PORT} --bind 127.0.0.1
