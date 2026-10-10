# The server's own browser for LEARN: a Chromium you sign in to through a web page
# (noVNC on port 6080), which the sync then reads LEARN with over its debugging port.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium xvfb x11vnc novnc websockify openbox socat \
        fonts-liberation fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY start.sh /start.sh
CMD ["/bin/sh", "/start.sh"]
