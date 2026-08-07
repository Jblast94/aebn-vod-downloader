FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    AEBNDL_HOST=0.0.0.0 \
    AEBNDL_PORT=8787 \
    AEBNDL_OUTPUT_DIR=/downloads \
    AEBNDL_WORK_DIR=/work

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY aebn_dl ./aebn_dl

RUN uv sync --frozen --no-dev

RUN mkdir -p /downloads /work

EXPOSE 8787

CMD ["uv", "run", "aebndl-web"]
