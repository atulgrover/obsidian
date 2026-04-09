#!/bin/bash

# Stop-all script for RAG2 services
# Stops all Docker Compose services.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "  Stopping RAG2 Services"
echo "=========================================="

echo ""
echo "--- Stopping Docker services ---"
cd "$SCRIPT_DIR"
docker compose down

echo ""
echo "=========================================="
echo "  All services stopped"
echo ""
echo "  To wipe data:  docker compose down -v"
echo "  To restart:    ./start-all.sh"
echo "=========================================="