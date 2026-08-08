FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
RUN python -m pip install --no-cache-dir --upgrade "pip==26.2.1" \
    && python -m pip install --no-cache-dir '.[rl]' \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/app/data/runs /app/app/data/audit \
    && chown -R app:app /app/app/data

USER 10001:10001

EXPOSE 8808
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8808"]
