#!/bin/bash

# Stop-all script for Dokuwiki and Header applications
# Stops all services started by start-all.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

echo "=========================================="
echo "  Stopping Dokuwiki and Header Services"
echo "=========================================="

# Function to stop a service by PID file
stop_service() {
    local pid_file="$1"
    local name="$2"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "✅ Stopped $name (PID: $pid)"
        else
            echo "⚠️  $name was not running (PID: $pid)"
        fi
        rm -f "$pid_file"
    else
        echo "⚠️  No PID file found for $name"
    fi
}

# Stop all services
echo ""
stop_service "$LOG_DIR/dokuwiki.pid" "Dokuwiki"
stop_service "$LOG_DIR/header-backend.pid" "Header Backend"
stop_service "$LOG_DIR/header-frontend.pid" "Header Frontend"

# Kill any remaining processes on the expected ports
echo ""
echo "--- Cleaning up any remaining processes ---"

for port in 8080 4000 5173; do
    pid=$(lsof -t -i :$port 2>/dev/null)
    if [ -n "$pid" ]; then
        kill $pid 2>/dev/null
        echo "🔪 Killed process on port $port (PID: $pid)"
    fi
done

echo ""
echo "=========================================="
echo "  All services stopped"
echo "=========================================="