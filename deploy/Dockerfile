# iScale web server for a small always-on box (CasaOS, any Docker host).
# Heavy 3D work (LingBot-Map + point-cloud analysis) can be left to a GPU computer: set
# CIVIL_3D=remote and CIVIL_WORKER_TOKEN, then run `civil worker` there (civil/worker.py).
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
# ejabberd 24.12 (Debian 13) carries the encrypted chat; python3 3.13 runs iScale
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d \
 && apt-get update && apt-get install -y --no-install-recommends \
      ejabberd python3 python3-venv ca-certificates tini libglib2.0-0 libgl1 libxcb1 \
 && rm -rf /var/lib/apt/lists/* /usr/sbin/policy-rc.d
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PYTHON=/usr/bin/python3 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY civil ./civil
COPY adapters ./adapters
COPY config ./config
COPY static ./static
RUN uv sync --frozen --no-dev && mkdir -p /data && chown -R ejabberd:ejabberd /data /app/config

# Debian's ejabberdctl only runs as root or as the ejabberd user: run everything as ejabberd.
ENV PATH=/app/.venv/bin:$PATH \
    CIVIL_DATA_DIR=/data \
    CIVIL_EJABBERDCTL=/usr/sbin/ejabberdctl \
    FORWARDED_ALLOW_IPS=* \
    PYTHONUNBUFFERED=1
USER ejabberd
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s CMD python3 -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8765/api/auth/state').status!=200)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["civil", "serve", "--host", "0.0.0.0", "--port", "8765"]
