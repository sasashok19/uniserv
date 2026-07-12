#!/bin/bash
# UniServe — stop all locally-started services (companion to dev-local.sh).
# Usage: ./scripts/dev-stop.sh
#
# Tries three things, in order, since process-name matching (pkill -f) is
# unreliable for Windows Java/Node processes from Git Bash/MSYS:
#   1. Kill the PIDs dev-local.sh recorded (if it's still running elsewhere).
#   2. pkill by command-line pattern (works on macOS/Linux, often on Git Bash).
#   3. Kill whatever is listening on our four ports (most reliable on Windows).

cd "$(dirname "${BASH_SOURCE[0]}")/.."
echo "Stopping UniServe local services..."

PID_FILE="scripts/.dev-local.pids"
if [ -f "$PID_FILE" ]; then
  while read -r pid; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

pkill -f "quarkus:dev" 2>/dev/null
pkill -f "uvicorn app.main" 2>/dev/null
pkill -f "next dev" 2>/dev/null
valkey-cli shutdown 2>/dev/null || redis-cli shutdown 2>/dev/null

# Windows fallback: pkill -f frequently can't see into Win32 process command
# lines from Git Bash, so also free the ports directly via PowerShell.
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]] && command -v powershell.exe > /dev/null 2>&1; then
  for port in 8080 8090 8001 3000 6379; do
    powershell.exe -NoProfile -Command \
      "Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -Expand OwningProcess -Unique | ForEach-Object { Stop-Process -Id \$_ -Force -ErrorAction SilentlyContinue }" \
      > /dev/null 2>&1
  done
fi

echo "Done."
