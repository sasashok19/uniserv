#!/bin/bash
# UniServe — single entry point for starting the dev stack.
#
# One environment flag, RUN_MODE, controls how: "local" runs every service as
# a bare process (scripts/dev-local.sh); "docker" runs the existing Docker
# Compose stack. Defaults to "local" per the current local-first phase —
# flip back to Docker any time once services are stable, either for one run:
#
#   RUN_MODE=docker ./scripts/dev.sh
#
# or persistently by adding `RUN_MODE=docker` to a root .env file.
#
# Usage: ./scripts/dev.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -f .env ]; then
  set -a; source .env; set +a
fi
RUN_MODE="${RUN_MODE:-local}"

case "$RUN_MODE" in
  local)
    echo "RUN_MODE=local — starting the local (no Docker) dev stack."
    exec ./scripts/dev-local.sh
    ;;
  docker)
    echo "RUN_MODE=docker — starting the Docker Compose dev stack."
    exec docker compose -f infrastructure/compose/docker-compose.dev.yml up --build
    ;;
  *)
    echo "ERROR: RUN_MODE must be 'local' or 'docker' (got: '$RUN_MODE')." >&2
    exit 1
    ;;
esac
