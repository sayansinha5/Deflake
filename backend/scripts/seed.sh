#!/bin/sh
# Create the Owner and demo accounts, load the allowlist, and load the
# finished flaky-shop scan when the database has no completed run.
# Safe to run more than once. This does not start a scan.
#
# Inside the API container (docker compose exec api sh):
#   sh scripts/seed.sh
set -eu
python scripts/create_owner.py
python scripts/seed_allowlist.py
python scripts/seed_completed_run.py
