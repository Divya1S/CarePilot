# Intensive Vibe Coding Capstone Project: Relay — Caregiver Concierge
FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App code (see .dockerignore for exclusions).
COPY . .

# Persist the SQLite DB outside the image (mount a volume at /data to keep state).
ENV RELAY_DB=/data/relay.db

EXPOSE 8000

# Respect the platform-provided $PORT (Render/Fly/Cloud Run) if present.
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
