#!/bin/sh
# A virtual screen, a window manager and Chromium on it, shared as a web page.
# The profile in /profile keeps the LEARN session between restarts.
export DISPLAY=:99 HOME=/profile
mkdir -p /profile/chromium
# Left behind when the container was stopped; Chromium refuses to start over them.
rm -f /profile/chromium/Singleton*
# The same for the virtual screen's lock, after a restart.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Stay signed in to LEARN across restarts. Chromium throws away a site's session
# cookies when it starts, unless it is set to reopen what was open last time.
python3 - <<'EOF'
import json
import pathlib

path = pathlib.Path("/profile/chromium/Default/Preferences")
path.parent.mkdir(parents=True, exist_ok=True)
prefs = json.loads(path.read_text()) if path.exists() else {}
prefs.setdefault("session", {})["restore_on_startup"] = 1
# A stop is not a crash: no "restore pages?" bubble over the sign-in page.
prefs.setdefault("profile", {})["exit_type"] = "Normal"
path.write_text(json.dumps(prefs))
EOF

Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
sleep 1
openbox &
x11vnc -display :99 -forever -shared -nopw -quiet -localhost -rfbport 5900 &
websockify --web /usr/share/novnc 6080 127.0.0.1:5900 &

# Chromium takes debugging connections on its own loopback only, so pass the
# dashboard's on to it. Port 9223 is reachable from the dashboard's container and
# is never published.
socat TCP-LISTEN:9223,fork,reuseaddr TCP:127.0.0.1:9222 &

exec chromium --no-sandbox --user-data-dir=/profile/chromium \
  --remote-debugging-port=9222 --no-first-run --no-default-browser-check \
  --disable-dev-shm-usage --password-store=basic --hide-crash-restore-bubble \
  --window-position=0,0 \
  --window-size=1280,800 "${LEARN_URL:-https://learn.uwaterloo.ca}"
