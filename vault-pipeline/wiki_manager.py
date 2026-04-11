"""
Wiki Manager — manages MWS client lifecycle and wiki operations.

Provides a singleton MWSClient instance and convenience functions
for wiki creation/deletion. Used by app.py at startup and throughout
the pipeline.

Environment variables:
  MWS_URL          — MWS base URL (default: http://mws:8080)
  MWS_ADMIN_USER    — MWS admin username (default: admin)
  MWS_ADMIN_PASSWORD — MWS admin password (default: 1234)
  MWS_DB_PATH       — Path to MWS SQLite database (default: /data/mws-store/database.sqlite)
  STORAGE_BACKEND   — "vault" (Obsidian files) or "wiki" (TiddlyWiki MWS)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from mws_client import MWSClient

logger = logging.getLogger("vault-pipeline")

# Singleton client instance
_client: Optional[MWSClient] = None

# Storage backend mode
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "vault").lower()
MWS_URL = os.environ.get("MWS_URL", "http://mws:8080")
MWS_ADMIN_USER = os.environ.get("MWS_ADMIN_USER", "admin")
MWS_ADMIN_PASSWORD = os.environ.get("MWS_ADMIN_PASSWORD", "1234")
MWS_DB_PATH = os.environ.get("MWS_DB_PATH", "/data/mws-store/database.sqlite")


def is_wiki_mode() -> bool:
    """Check if the pipeline is configured to use TiddlyWiki MWS backend."""
    return STORAGE_BACKEND == "wiki"


def get_client() -> MWSClient:
    """Get or create the MWS client singleton.

    Called for every dual-write operation (vault + wiki mirroring).
    """
    global _client
    if _client is None:
        _client = MWSClient(
            base_url=MWS_URL,
            username=MWS_ADMIN_USER,
            password=MWS_ADMIN_PASSWORD,
            db_path=MWS_DB_PATH,
        )
        logger.info(f"MWS client created for {MWS_URL}")
    return _client


async def authenticate() -> None:
    """Authenticate with MWS. Called at startup for dual-write mode.

    Always authenticates (even in vault mode) because dual-write needs
    MWS access regardless of STORAGE_BACKEND.
    """
    client = get_client()
    await client.authenticate()
    logger.info("MWS authentication successful — dual-write enabled (vault + TiddlyWiki)")


async def ensure_wiki(slug: str, description: str = "") -> None:
    """Ensure a wiki exists for the given slug. Creates it if missing.

    Args:
        slug: Document slug (used as the wiki/recipe name).
        description: Optional wiki description.
    """
    client = get_client()
    from wiki_io import init_wiki
    await init_wiki(client, slug, description)


async def delete_wiki(slug: str) -> None:
    """Delete a wiki and all its tiddlers.

    Args:
        slug: Document slug (wiki/recipe name).
    """
    client = get_client()
    await client.delete_wiki(slug)
    logger.info(f"Deleted wiki: {slug}")


async def health_check() -> bool:
    """Check if MWS is reachable and authenticated."""
    client = get_client()
    return await client.health_check()


async def close() -> None:
    """Close the MWS client connection."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None