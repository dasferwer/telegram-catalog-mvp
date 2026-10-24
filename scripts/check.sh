#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv run --directory backend ruff check shop tests migrations ../scripts
uv run --directory backend ruff format --check shop tests migrations ../scripts
uv run --directory backend mypy shop
uv run --directory backend pytest tests/test_security.py -q
npm --prefix frontend ci
npm --prefix frontend run typecheck
NEXT_TELEMETRY_DISABLED=1 npm --prefix frontend run build
docker compose -f compose.yml -f compose.test.yml build
docker compose -f compose.yml -f compose.test.yml up -d --wait --scale web=2 --scale api=2 --scale bot=2
docker compose -f compose.yml -f compose.test.yml run --rm --no-deps tests
python3 scripts/test-runtime.py
npm --prefix frontend run test:e2e
