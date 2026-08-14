FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

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
    && mkdir -p /app/app/data/runs /app/app/data/audit /app/app/data/runtime \
    && chown -R app:app /app/app/data

USER 10001:10001

EXPOSE 8808
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8808"]
