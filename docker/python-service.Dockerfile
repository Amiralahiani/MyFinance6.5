FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Market Watch is read from the public official site through the repository's
# Playwright reader.  The API image therefore needs Node.js and Chromium too;
# without them, live quotes always fail safely as "unavailable" in Docker.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY chat/web/package.json chat/web/package-lock.json ./chat/web/
RUN cd chat/web \
    && npm ci \
    && npx playwright install --with-deps chromium

COPY . .
RUN uv sync --frozen --all-packages --no-dev

CMD ["uv", "run", "--no-sync", "python", "chat/scripts/run_orchestrator.py", "--host", "0.0.0.0"]
