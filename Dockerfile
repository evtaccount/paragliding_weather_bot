FROM python:3.12-slim

# fonts-dejavu-core → Cyrillic glyphs for the Pillow charts; tzdata → correct local date
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# run as non-root; /app/data holds the writable SQLite database (a named volume
# mounts here and inherits this ownership, so the app user can persist sites,
# routes, settings and the model choice)
RUN mkdir -p /app/data && useradd -m -u 10001 app && chown -R app /app
USER app

# docker-compose's caddy waits on "condition: service_healthy" for exactly
# this — without it, caddy starts as soon as the container is running, not
# once uvicorn actually accepts connections.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request as u; \
        u.urlopen('http://127.0.0.1:' + os.environ.get('API_PORT', '8080') + '/api/health', timeout=3)"

CMD ["python", "-u", "app.py"]
