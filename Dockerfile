FROM python:3.12-slim

# fonts-dejavu-core → Cyrillic glyphs for the Pillow charts; tzdata → correct local date
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# run as non-root
RUN useradd -m -u 10001 app && chown -R app /app
USER app

CMD ["python", "-u", "bot.py"]
