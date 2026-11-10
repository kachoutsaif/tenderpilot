FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dépendances d'abord : Docker garde cette couche en cache tant que pyproject.toml ne change pas
COPY pyproject.toml README.md ./
COPY src ./src
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt && pip install --no-cache-dir --no-deps .

COPY scripts ./scripts
COPY tests/fixtures ./tests/fixtures

# Utilisateur non-root (bonne pratique de sécurité)
RUN useradd --create-home app && mkdir -p /models && chown app /models
USER app

EXPOSE 8000
CMD ["uvicorn", "tenderpilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
