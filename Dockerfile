# webapp/dist в git не лежит (.gitignore) — его собирают. Отдельный этап на
# Node нужен, чтобы node_modules и тулчейн сборки не ехали в финальный образ:
# приложение отдаёт pgbot (api.py монтирует webapp/dist на "/"), а из всей
# сборки ему нужен только результат.
FROM node:22-slim AS webapp
WORKDIR /build
# package*.json отдельным слоем: npm ci переустанавливается только когда
# меняются зависимости, а не на каждую правку в webapp/src.
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build

FROM python:3.12-slim

# fonts-dejavu-core → Cyrillic glyphs for the Pillow charts; tzdata → correct local date
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Результат этапа webapp — обязательно ВЫШЕ единственного `chown -R` ниже.
# Дело не в доступе: файлы приезжают с режимом 644 и читаются кем угодно,
# образ с этой строкой после USER app отдаёт GET / → 200 как ни в чём не
# бывало. Дело в том, что одним проходом chown владелец всего /app остаётся
# однородным: выравнивать потом пришлось бы вторым `chown -R app /app`, а он
# переписывает метаданные каждого файла и кладёт их копии в отдельный слой.
COPY --from=webapp /build/dist ./webapp/dist

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
