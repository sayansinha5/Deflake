#!/bin/sh
# Apply Alembic migrations. Safe to run more than once.
#
# Inside the API container (docker compose exec api sh):
#   sh scripts/migrate.sh
set -eu
alembic upgrade head
