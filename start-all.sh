#!/bin/bash

# Start-all script for Dokuwiki and Header applications
# Starts all services in background

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "  Starting Dokuwiki and Header Services"
echo "=========================================="

# Function to check if a port is in use
port_in_use() {
    lsof -i :"$1" >/dev/null 2>&1
}

# Function to wait for a service to start
wait_for_service() {
    local port="$1"
    local name="$2"
    local max_attempts=30
    local attempt=0

    while ! port_in_use "$port" && [ $attempt -lt $max_attempts ]; do
        sleep 0.5
        ((attempt++))
    done

    if port_in_use "$port"; then
        echo "✅ $name started on port $port"
        return 0
    else
        echo "❌ Failed to start $name on port $port"
        return 1
    fi
}

# ============================================
# Start Dokuwiki (PHP built-in server)
# ============================================
echo ""
echo "--- Starting Dokuwiki ---"
DOKUWIKI_PORT=8080

if port_in_use $DOKUWIKI_PORT; then
    echo "⚠️  Port $DOKUWIKI_PORT is already in use. Skipping Dokuwiki."
else
    cd "$SCRIPT_DIR/Dokuwiki"
    php -d memory_limit=512M -S localhost:$DOKUWIKI_PORT > "$LOG_DIR/dokuwiki.log" 2>&1 &
    DOKUWIKI_PID=$!
    echo "DOKUWIKI_PID=$DOKUWIKI_PID" > "$LOG_DIR/dokuwiki.pid"
    wait_for_service $DOKUWIKI_PORT "Dokuwiki"
fi

# ============================================
# Start Header Backend (SQLite API server)
# ============================================
echo ""
echo "--- Starting Header Backend ---"
BACKEND_PORT=4000

if port_in_use $BACKEND_PORT; then
    echo "⚠️  Port $BACKEND_PORT is already in use. Skipping Header Backend."
else
    cd "$SCRIPT_DIR/Header/neon-backend"

    # Check if .env exists, copy from example if not
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            echo "📝 Created .env from .env.example"
        fi
    fi

    node sqlite-server.js > "$LOG_DIR/header-backend.log" 2>&1 &
    BACKEND_PID=$!
    echo "BACKEND_PID=$BACKEND_PID" > "$LOG_DIR/header-backend.pid"
    wait_for_service $BACKEND_PORT "Header Backend"
fi

# ============================================
# Start Header Frontend (Vite dev server)
# ============================================
echo ""
echo "--- Starting Header Frontend ---"
FRONTEND_PORT=5173

if port_in_use $FRONTEND_PORT; then
    echo "⚠️  Port $FRONTEND_PORT is already in use. Skipping Header Frontend."
else
    cd "$SCRIPT_DIR/Header"

    # Check if .env exists for frontend
    if [ ! -f ".env" ] && [ -f ".env.example" ]; then
        cp .env.example .env
        echo "📝 Created .env from .env.example"
    fi

    bun run dev > "$LOG_DIR/header-frontend.log" 2>&1 &
    FRONTEND_PID=$!
    echo "FRONTEND_PID=$FRONTEND_PID" > "$LOG_DIR/header-frontend.pid"
    wait_for_service $FRONTEND_PORT "Header Frontend"
fi

# ============================================
# Summary
# ============================================
echo ""
echo "=========================================="
echo "  Services Started"
echo "=========================================="
echo ""
echo "  📚 Dokuwiki:     http://localhost:$DOKUWIKI_PORT"
echo "  🔧 Header API:   http://localhost:$BACKEND_PORT"
echo "  🌐 Header UI:    http://localhost:$FRONTEND_PORT"
echo ""
echo "  Logs directory: $LOG_DIR"
echo ""
echo "  To stop all services, run: ./stop-all.sh"
echo "=========================================="