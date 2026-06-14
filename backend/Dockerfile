# Dashboard / REST API backend (app.main). Lean image — core deps only, no voice/ML stack.
# (The voice agent runs separately; see README.)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-core.txt .
RUN pip install -r requirements-core.txt

COPY app ./app

EXPOSE 8000
# Hosts (Railway/Render/Fly) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
