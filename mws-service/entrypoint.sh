#!/bin/sh
set -e

DATA_DIR="${MWS_DATA_DIR:-/data/store}"
ADMIN_USER="${MWS_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${MWS_ADMIN_PASSWORD:-1234}"

# Initialize MWS store if not already done
if [ ! -f "$DATA_DIR/.mws-initialized" ]; then
    echo "Initializing MWS store..."
    cd /data
    npx mws init-store --admin-password "$ADMIN_PASSWORD" 2>&1 || true
    touch "$DATA_DIR/.mws-initialized"
    echo "MWS store initialized."
fi

echo "Starting TiddlyWiki MWS on port ${MWS_PORT:-8080}..."
exec npx mws listen --listener "host=0.0.0.0" "port=${MWS_PORT:-8080}"