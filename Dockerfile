FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# The tool the LEARN sync drives the server's browser with, in its own environment.
RUN uv venv /opt/harness \
    && uv pip install --python /opt/harness/bin/python browser-harness==0.1.13
# It keeps its working files under HOME, which the container's user must be able to write.
ENV BROWSER_USE_EXECUTABLE=/opt/harness/bin/browser-harness HOME=/tmp

COPY backend ./backend
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["/app/.venv/bin/study-agent", "dashboard", "--host", "0.0.0.0", "--no-open"]
