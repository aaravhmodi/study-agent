# Claude Code plus what the jobs need to run Study Agent's tests: git, uv and Python.
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
RUN npm install -g @anthropic-ai/claude-code

# The image's "node" user (uid 1000, the same as yours on the server, so it can read the
# mounted deploy key); Claude Code is never run as root.
USER node
ENV HOME=/home/node HARNESS_WORK=/work UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/work/python
WORKDIR /home/node/harness
COPY --chown=node server.py ./
COPY --chown=node jobs ./jobs

EXPOSE 8790
CMD ["python3", "server.py"]
