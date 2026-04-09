#!/bin/bash

# Start-all script for RAG2 services
# All microservices run via Docker Compose.
# Run this script to start everything.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "  Starting RAG2 Services"
echo "=========================================="

# ============================================
# Start all Docker services
# ============================================
echo ""
echo "--- Starting Docker services ---"
cd "$SCRIPT_DIR"
docker compose up -d

echo ""
echo "--- Waiting for services to be healthy ---"
sleep 5

# ============================================
# Check service status
# ============================================
echo ""
echo "=========================================="
echo "  RAG2 Services"
echo "=========================================="
echo ""
echo "  Docker services (all via docker compose):"
echo ""
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || docker compose ps
echo ""
echo "  Endpoints:"
echo "    📄 LiteParse:      http://localhost:5001"
echo "    🌳 PageIndex:      http://localhost:5002"
echo "    ✂️  SemChunk:       http://localhost:5003"
echo "    📦 Vault Pipeline: http://localhost:5004"
echo "    🌐 RAG2-Web:       http://localhost:5173"
echo "    🧠 LightRAG:      http://localhost:8020"
echo "    🔍 SBERT:         http://localhost:8021"
echo "    🐘 Postgres:       localhost:5432"
echo ""
echo "  Vault directory: /vault (inside container), or set VAULT_ROOT"
echo ""
echo "  To stop:        ./stop-all.sh"
echo "  To wipe data:   docker compose down -v"
echo "  To view logs:   docker compose logs -f [service]"
echo "=========================================="