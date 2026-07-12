#!/bin/bash
# UniServe — Local development startup (no Docker)
# Usage: ./scripts/dev-local.sh
# Requires: Java 21, Maven 3.9+, Python 3.11+, Node 20+, Valkey (or Redis)
#
# Ports match Docker mode exactly (see README.md "Ports"), so nothing
# downstream (dashboard, .http test stubs, docs) needs to change when you
# flip RUN_MODE between "local" and "docker" (see scripts/dev.sh).
#   api-gateway 8080 | db-writer 8090 | ai-core 8001 | dashboard 3000 | valkey 6379

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # always run from repo root
export APP_ENV=development

# JAVA_HOME often lags behind a fresh JDK install/upgrade (Windows env vars only
# propagate to *new* processes, and a stale JAVA_HOME from a since-removed JDK
# is a real, seen-in-practice failure mode: `mvn` refuses to run at all if
# JAVA_HOME points at a directory that no longer exists). If it's unset or
# broken, try to auto-detect a JDK 21 install in the usual places rather than
# fail with a confusing Maven error.
if [ -z "${JAVA_HOME:-}" ] || [ ! -x "${JAVA_HOME}/bin/java" ]; then
  for candidate in \
    "/c/Program Files/Java"/jdk-21* \
    "/c/Program Files/Eclipse Adoptium"/jdk-21* \
    "/c/Program Files/Java"/jdk-21 \
    /usr/lib/jvm/*-21* \
    /opt/java/jdk-21*
  do
    if [ -x "$candidate/bin/java" ]; then
      export JAVA_HOME="$candidate"
      export PATH="$JAVA_HOME/bin:$PATH"
      echo "JAVA_HOME was unset/stale — auto-detected and using: $JAVA_HOME"
      break
    fi
  done
fi

# Same problem, same fix, for Maven: a fresh install's PATH entry may not have
# reached this shell yet (new PATH entries only apply to *new* processes on
# Windows), so fall back to the usual install locations if `mvn` isn't found.
if ! command -v mvn > /dev/null 2>&1; then
  for candidate in \
    "/c/Program Files/apache-maven"*/bin \
    "/c/Program Files (x86)/apache-maven"*/bin \
    /usr/local/apache-maven*/bin \
    /opt/apache-maven*/bin
  do
    if [ -x "$candidate/mvn" ]; then
      export PATH="$candidate:$PATH"
      echo "mvn was not on PATH — auto-detected and using: $candidate"
      break
    fi
  done
fi

PIDS=()
PID_FILE="scripts/.dev-local.pids"
: > "$PID_FILE"

# Common log (Feature 01/ORCHESTRATOR observability convention): every
# service's individual log (scripts/<service>.log) is unchanged, but each
# line is *also* tee'd into this one file with a "[service]" prefix, so a
# single `tail -f scripts/combined.log` shows everything interleaved in the
# order it happened, without needing to tail 4 separate files.
COMBINED_LOG="scripts/combined.log"
: > "$COMBINED_LOG"

record_pid() {
  echo "$1" >> "$PID_FILE"
  PIDS+=("$1")
}

port_open() {
  # Bash's /dev/tcp pseudo-device — no nc/curl dependency, works in Git Bash too.
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- 3<&-
}

wait_for() {
  local url="$1" name="$2" tries="${3:-30}"
  echo "Waiting for $name to be ready..."
  for _ in $(seq 1 "$tries"); do
    if curl -sf "$url" > /dev/null 2>&1; then
      echo "$name ready."
      return 0
    fi
    sleep 2
  done
  echo "ERROR: $name did not become ready at $url after $((tries * 2))s." >&2
  return 1
}

# ------------------------------------------------------------------
# Valkey / Redis (event bus) — required by every backend service.
# ------------------------------------------------------------------
echo "Checking Valkey/Redis on port 6379..."
if port_open 6379; then
  echo "Something is already listening on 6379 — assuming it's Valkey/Redis (e.g. a Memurai service, WSL redis, or a prior run). Skipping start."
elif command -v valkey-server > /dev/null 2>&1; then
  echo "Starting Valkey..."
  valkey-server --daemonize yes --port 6379 --loglevel warning
elif command -v redis-server > /dev/null 2>&1; then
  echo "valkey-server not found; starting redis-server instead..."
  redis-server --daemonize yes --port 6379 --loglevel warning
else
  echo "" >&2
  echo "ERROR: neither valkey-server nor redis-server was found on PATH." >&2
  echo "See LOCAL_DEV.md 'Installing Valkey/Redis' for install instructions" >&2
  echo "for your OS (Homebrew on macOS/Linux, WSL2 or Memurai on Windows)." >&2
  echo "" >&2
  exit 1
fi

# ------------------------------------------------------------------
# DB Writer (port 8090) — must be ready before api-gateway/ai-core start,
# since both call it.
# ------------------------------------------------------------------
echo "Starting DB Writer (port 8090)..."
mkdir -p services/db-writer/data
(
  cd services/db-writer
  set -a; [ -f .env.local ] && source .env.local; set +a
  exec mvn quarkus:dev
) > >(tee -a scripts/db-writer.log | sed -u "s/^/[db-writer] /" >> "$COMBINED_LOG") 2>&1 &
record_pid $!

wait_for "http://localhost:8090/q/health/ready" "DB Writer"

# ------------------------------------------------------------------
# API Gateway (port 8080)
# ------------------------------------------------------------------
echo "Starting API Gateway (port 8080)..."
(
  cd services/api-gateway
  set -a; [ -f .env.local ] && source .env.local; set +a
  exec mvn quarkus:dev
) > >(tee -a scripts/api-gateway.log | sed -u "s/^/[api-gateway] /" >> "$COMBINED_LOG") 2>&1 &
record_pid $!

# ------------------------------------------------------------------
# AI Core (port 8001)
# ------------------------------------------------------------------
echo "Starting AI Core (port 8001)..."
(
  cd services/ai-core
  if [ ! -d .venv ]; then
    python3 -m venv .venv
  fi
  # Windows venvs use Scripts/activate; POSIX venvs use bin/activate.
  if [ -f .venv/Scripts/activate ]; then
    source .venv/Scripts/activate
  else
    source .venv/bin/activate
  fi
  # Non-fatal: on some Python versions (e.g. 3.14 at the time this was
  # written) pydantic-core has no prebuilt wheel yet and fails to build from
  # source without a Rust toolchain. If the venv already has a working
  # install (as it will after the first successful run), keep going instead
  # of aborting the whole script over a reinstall that isn't actually needed.
  pip install -r requirements.txt -q || echo "WARNING: pip install had errors — continuing with whatever is already in .venv (see scripts/ai-core.log)"
  exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
) > >(tee -a scripts/ai-core.log | sed -u "s/^/[ai-core] /" >> "$COMBINED_LOG") 2>&1 &
record_pid $!

# ------------------------------------------------------------------
# Dashboard (port 3000)
# ------------------------------------------------------------------
echo "Starting Dashboard (port 3000)..."
(
  cd apps/dashboard
  npm install --silent
  exec npm run dev
) > >(tee -a scripts/dashboard.log | sed -u "s/^/[dashboard] /" >> "$COMBINED_LOG") 2>&1 &
record_pid $!

echo ""
echo "Waiting for API Gateway and AI Core to be ready..."
wait_for "http://localhost:8080/q/health/ready" "API Gateway" || true
wait_for "http://localhost:8001/q/health/ready" "AI Core" || true

echo ""
echo "All services started:"
echo "  API Gateway : http://localhost:8080"
echo "  DB Writer   : http://localhost:8090"
echo "  AI Core     : http://localhost:8001"
echo "  Dashboard   : http://localhost:3000"
echo ""
echo "Per-service logs: scripts/{db-writer,api-gateway,ai-core,dashboard}.log"
echo "Combined log (all services, tagged, in order): scripts/combined.log"
echo "  tail -f scripts/combined.log"
echo "Press Ctrl+C to stop all services (or run ./scripts/dev-stop.sh from another shell)."

cleanup() {
  echo ""
  echo "Stopping services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  valkey-cli shutdown 2>/dev/null || redis-cli shutdown 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "All services stopped."
}
trap cleanup INT TERM
wait
