FROM python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS build
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN pip install --no-cache-dir uv==0.11.17 && uv sync --frozen --no-dev --no-cache
COPY backend/shop ./shop
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
FROM build AS test
RUN uv sync --frozen --no-cache
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
COPY backend/tests ./tests
CMD [".venv/bin/pytest", "-q"]
FROM python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip* /usr/local/bin/pip*
COPY --from=build /app /app
USER 10001:10001
CMD ["uvicorn", "shop.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "32"]
