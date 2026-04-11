"""
MWS Client — HTTP client for TiddlyWiki MultiWikiServer (MWS).

Handles authentication via SQLite session injection, wiki (recipe) CRUD,
and tiddler CRUD via the MWS REST API.

Each PDF document maps to its own wiki instance (recipe) in MWS.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("vault-pipeline")


class MWSAuthError(Exception):
    """Raised when MWS authentication fails."""


class MWSError(Exception):
    """Raised when an MWS API call fails."""


class MWSClient:
    """Async HTTP client for TiddlyWiki MultiWikiServer.

    Authentication uses direct SQLite session injection — we insert a session
    row into the MWS database (shared via Docker volume) and use the session_id
    as a cookie. This bypasses the OPAQUE protocol that MWS uses for browser login.

    Usage:
        client = MWSClient("http://mws:8080", db_path="/data/mws-store/database.sqlite")
        await client.authenticate()
        await client.create_wiki("my-doc")
        await client.put_tiddler("my-doc", "Hello", text="Hello world!", tags="hello test")
    """

    def __init__(
        self,
        base_url: str,
        username: str = "admin",
        password: str = "1234",
        db_path: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.db_path = db_path or os.environ.get("MWS_DB_PATH", "")
        self.session_cookie: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    # ──────────────────────────────────────────────────────────────
    # Authentication via SQLite session injection
    # ──────────────────────────────────────────────────────────────

    async def authenticate(self) -> None:
        """Authenticate with MWS by injecting a session into the SQLite database.

        Since MWS uses the OPAQUE protocol for browser-based login (which we
        can't implement in Python), we bypass it by directly inserting a session
        row into the MWS SQLite database. The MWS data volume is shared between
        the MWS container and the vault-pipeline container.
        """
        if not self.db_path:
            # Try default path
            self.db_path = "/data/mws-store/database.sqlite"

        if not Path(self.db_path).exists():
            raise MWSAuthError(
                f"MWS database not found at {self.db_path}. "
                "Ensure the mws_data volume is mounted in the vault-pipeline container."
            )

        session_id = self._inject_session()
        if session_id:
            self.session_cookie = f"session={session_id}"
            logger.info(f"MWS authentication successful (SQLite session injection)")
        else:
            raise MWSAuthError("Failed to inject MWS session into SQLite database")

    def _inject_session(self) -> Optional[str]:
        """Insert a session row into the MWS SQLite database and return the session_id.

        MWS stores sessions in the 'sessions' table with columns:
          session_id (TEXT PK), created_at (DATETIME), last_accessed (DATETIME),
          session_key (TEXT), user_id (TEXT FK → users)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")  # Use WAL mode for better concurrency
            cursor = conn.cursor()

            # Find the admin user
            cursor.execute(
                "SELECT user_id FROM users WHERE username = ?", (self.username,)
            )
            row = cursor.fetchone()
            if not row:
                logger.error(f"MWS user '{self.username}' not found in database")
                conn.close()
                return None
            user_id = row[0]

            # Delete any existing sessions for this user (clean up stale sessions)
            cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

            # Create a new session
            session_id = secrets.token_urlsafe(16)
            session_key = secrets.token_urlsafe(32)
            now = time.strftime("%Y-%m-%dT%H:%M:%S.000+00:00", time.gmtime())

            cursor.execute(
                "INSERT INTO sessions (session_id, created_at, last_accessed, session_key, user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, now, now, session_key, user_id),
            )
            conn.commit()
            conn.close()

            logger.info(f"Injected MWS session for user '{self.username}' (session_id={session_id})")
            return session_id

        except sqlite3.Error as e:
            logger.error(f"SQLite error injecting MWS session: {e}")
            return None

    async def _ensure_auth(self) -> None:
        """Ensure we have a valid session cookie, re-authenticate if needed."""
        if not self.session_cookie:
            await self.authenticate()

    # ──────────────────────────────────────────────────────────────
    # Low-level request helper
    # ──────────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Optional[Dict] = None,
        body_str: Optional[str] = None,
        content_type: str = "application/json",
        headers: Optional[Dict[str, str]] = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        """Make an authenticated request to MWS, auto-refreshing session on 401."""
        await self._ensure_auth()

        client = await self._get_client()
        req_headers = {
            "Content-Type": content_type,
            "X-Requested-With": "fetch",
        }
        if self.session_cookie:
            req_headers["Cookie"] = self.session_cookie

        # Determine Referer based on path
        # MWS validates that the Referer recipe matches the URL recipe for tiddler writes.
        # No trailing slash! MWS compares Referer recipe name against the URL recipe name,
        # and a trailing slash causes a mismatch → 403.
        if path.startswith("/admin/"):
            req_headers["Referer"] = f"{self.base_url}/admin/"
        elif "/recipe/" in path or "/bag/" in path:
            # Extract recipe/bag name from path for Referer
            # e.g. /recipe/my-wiki/tiddlers/... → Referer: /wiki/my-wiki
            parts = path.split("/")
            if len(parts) >= 3:
                wiki_name = parts[2]
                req_headers["Referer"] = f"{self.base_url}/wiki/{wiki_name}"

        if headers:
            req_headers.update(headers)

        # Build request body
        if body_str is not None:
            # Raw string body (for tiddler saves)
            resp = await client.request(
                method,
                f"{self.base_url}{path}",
                content=body_str,
                headers=req_headers,
            )
        elif json_data is not None:
            resp = await client.request(
                method,
                f"{self.base_url}{path}",
                json=json_data,
                headers=req_headers,
            )
        else:
            resp = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=req_headers,
            )

        if resp.status_code == 401 and retry_auth:
            # Session expired; re-authenticate and retry once
            self.session_cookie = None
            await self.authenticate()
            req_headers["Cookie"] = self.session_cookie
            if body_str is not None:
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    content=body_str,
                    headers=req_headers,
                )
            elif json_data is not None:
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json_data,
                    headers=req_headers,
                )
            else:
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=req_headers,
                )

        return resp

    # ──────────────────────────────────────────────────────────────
    # Wiki (Recipe) CRUD
    # ──────────────────────────────────────────────────────────────

    async def create_wiki(self, slug: str, description: str = "") -> Dict[str, Any]:
        """Create a new wiki (recipe + bag) in MWS.

        Each PDF document gets its own wiki. The slug becomes the recipe name.
        Also sets up ACL entries so the wiki is viewable by all users.

        Returns:
            Dict with 'recipe' and 'bag' names.
        """
        bag_name = f"bag-{slug}"

        # Create the bag
        resp = await self._request(
            "POST",
            "/admin/bag_create_or_update",
            json_data={
                "bag_name": bag_name,
                "description": description or f"Bag for document {slug}",
                "create_only": True,
            },
        )
        if resp.status_code not in (200, 201, 204):
            # Bag may already exist — that's OK
            logger.debug(f"Bag creation returned {resp.status_code}: {resp.text[:200]}")

        # Create the recipe referencing the bag
        resp = await self._request(
            "POST",
            "/admin/recipe_create_or_update",
            json_data={
                "recipe_name": slug,
                "description": description or f"Wiki for document {slug}",
                "bag_names": [{"bag_name": bag_name, "with_acl": True}],
                "plugin_names": [
                    "$:/plugins/tiddlywiki/markdown",
                    "$:/themes/tiddlywiki/vanilla",
                    "$:/themes/tiddlywiki/snowwhite",
                ],
                "skip_required_plugins": False,
                "skip_core": False,
                "preload_store": False,
                "custom_wiki": None,
                "create_only": True,
            },
        )
        if resp.status_code not in (200, 201, 204):
            # Recipe may already exist — that's OK
            logger.debug(f"Recipe creation returned {resp.status_code}: {resp.text[:200]}")

        # Set up ACL so all users can read/write the wiki
        await self._ensure_acl(slug, bag_name)

        logger.info(f"Created wiki: {slug}")
        return {"recipe": slug, "bag": bag_name}

    async def _ensure_acl(self, recipe_name: str, bag_name: str) -> None:
        """Set up ACL entries so all users can read/write the wiki.

        MWS requires ACL entries for non-admin users to access wikis.
        Without this, wikis return 403 "no read permission" for anonymous users.
        """
        # Look up role IDs from the MWS database
        role_ids = self._get_role_ids()
        acl_entries = []
        for role_id in role_ids:
            acl_entries.append({"role_id": role_id, "permission": "READ"})
            acl_entries.append({"role_id": role_id, "permission": "WRITE"})

        # Set recipe ACL
        await self._request(
            "POST",
            "/admin/recipe_acl_update",
            json_data={"recipe_name": recipe_name, "acl": acl_entries},
        )

        # Set bag ACL
        await self._request(
            "POST",
            "/admin/bag_acl_update",
            json_data={"bag_name": bag_name, "acl": acl_entries},
        )
        logger.debug(f"Set ACL for wiki: {recipe_name}")

    def _get_role_ids(self) -> List[str]:
        """Look up all role IDs from the MWS SQLite database.

        Since the mws_data volume is shared with the vault-pipeline container,
        we can read the roles table directly. The default MWS installation
        creates ADMIN and USER roles.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            cursor.execute("SELECT role_id FROM roles")
            rows = cursor.fetchall()
            conn.close()
            if rows:
                return [row[0] for row in rows]
        except sqlite3.Error as e:
            logger.warning(f"Could not read role IDs from MWS database: {e}")

        logger.warning("Could not look up role IDs, skipping ACL setup")
        return []

    async def delete_wiki(self, slug: str) -> None:
        """Delete a wiki (recipe + bag) and all its tiddlers."""
        # Delete the recipe first
        resp = await self._request(
            "POST",
            "/admin/recipe_delete",
            json_data={"recipe_name": slug},
        )
        if resp.status_code not in (200, 201, 204):
            logger.warning(f"Recipe deletion returned {resp.status_code}: {resp.text[:200]}")

        # Delete the bag
        bag_name = f"bag-{slug}"
        resp = await self._request(
            "POST",
            "/admin/bag_delete",
            json_data={"bag_name": bag_name},
        )
        if resp.status_code not in (200, 201, 204):
            logger.warning(f"Bag deletion returned {resp.status_code}: {resp.text[:200]}")

        logger.info(f"Deleted wiki: {slug}")

    async def wiki_exists(self, slug: str) -> bool:
        """Check if a wiki (recipe) exists."""
        resp = await self._request("GET", f"/recipe/{slug}/status")
        return resp.status_code == 200

    async def list_wikis(self) -> List[str]:
        """List all wiki (recipe) names."""
        resp = await self._request(
            "POST",
            "/admin/index_json",
            json_data={},
        )
        if resp.status_code != 200:
            logger.warning(f"Failed to list wikis: {resp.status_code}")
            return []
        data = resp.json()
        if isinstance(data, dict) and "recipes" in data:
            return [r["recipe_name"] for r in data["recipes"]]
        return []

    # ──────────────────────────────────────────────────────────────
    # Tiddler CRUD
    # ──────────────────────────────────────────────────────────────

    async def put_tiddler(
        self,
        recipe: str,
        title: str,
        *,
        text: str = "",
        tags: str = "",
        tiddler_type: str = "text/vnd.tiddlywiki",
        fields: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create or update a tiddler in a wiki.

        Args:
            recipe: Wiki (recipe) name — typically the document slug.
            title: Tiddler title (unique within the wiki).
            text: Tiddler body content (wiki-text markup).
            tags: Space-separated tags, use [[brackets]] for multi-word.
            tiddler_type: Content type, default text/vnd.tiddlywiki.
            fields: Custom fields dict (all values must be strings).

        Returns:
            Response dict with bag_name and revision_id.
        """
        encoded_title = quote(title, safe="")

        # MWS expects a FLAT JSON object where all values are strings.
        # Custom fields go at the top level alongside title/text/type/tags,
        # NOT nested under a "fields" key.
        tiddler_data: Dict[str, str] = {
            "title": title,
            "text": text,
            "type": tiddler_type,
        }
        if tags:
            tiddler_data["tags"] = tags
        if fields:
            for k, v in fields.items():
                tiddler_data[k] = str(v)

        # MWS expects JSON body for tiddler saves
        resp = await self._request(
            "PUT",
            f"/recipe/{recipe}/tiddlers/{encoded_title}",
            json_data=tiddler_data,
        )
        if resp.status_code not in (200, 201, 204):
            raise MWSError(
                f"PUT tiddler '{title}' failed: {resp.status_code} {resp.text[:300]}"
            )

        try:
            return resp.json()
        except Exception:
            return {"status": "ok", "status_code": resp.status_code}

    async def get_tiddler(self, recipe: str, title: str) -> Optional[Dict[str, Any]]:
        """Get a tiddler by title. Returns None if not found."""
        encoded_title = quote(title, safe="")
        resp = await self._request("GET", f"/recipe/{recipe}/tiddlers/{encoded_title}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise MWSError(f"GET tiddler '{title}' failed: {resp.status_code}")
        return resp.json()

    async def list_tiddlers(self, recipe: str, filter_expr: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all tiddlers in a wiki, optionally filtered.

        Args:
            recipe: Wiki (recipe) name.
            filter_expr: Optional TiddlyWiki filter expression.
        """
        params = {}
        if filter_expr:
            params["filter"] = filter_expr
        resp = await self._request(
            "GET",
            f"/recipe/{recipe}/tiddlers.json",
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise MWSError(f"List tiddlers failed: {resp.status_code}")
        return resp.json()

    async def delete_tiddler(self, recipe: str, title: str) -> None:
        """Delete a tiddler from a wiki."""
        encoded_title = quote(title, safe="")
        resp = await self._request("DELETE", f"/recipe/{recipe}/tiddlers/{encoded_title}")
        if resp.status_code not in (200, 204):
            raise MWSError(f"DELETE tiddler '{title}' failed: {resp.status_code}")

    async def put_tiddlers_batch(
        self,
        recipe: str,
        tiddlers: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Create or update multiple tiddlers in batch.

        Args:
            recipe: Wiki (recipe) name.
            tiddlers: List of tiddler dicts, each with at least 'title' and 'text'.
        """
        # MWS doesn't have a native batch endpoint, so save one by one
        results = []
        for t in tiddlers:
            title = t.pop("title")
            text = t.pop("text", "")
            tags = t.pop("tags", "")
            fields = t  # remaining keys are custom fields
            result = await self.put_tiddler(recipe, title, text=text, tags=tags, fields=fields)
            results.append(result)
        return results

    # ──────────────────────────────────────────────────────────────
    # JSON tiddler helpers
    # ──────────────────────────────────────────────────────────────

    async def put_json_tiddler(
        self,
        recipe: str,
        title: str,
        data: Dict[str, Any],
        tags: str = "",
    ) -> Dict[str, Any]:
        """Store a JSON blob as a tiddler with type application/json."""
        text = json.dumps(data, ensure_ascii=False, indent=2)
        return await self.put_tiddler(
            recipe, title,
            text=text,
            tags=tags,
            tiddler_type="application/json",
        )

    async def get_json_tiddler(self, recipe: str, title: str) -> Optional[Dict[str, Any]]:
        """Retrieve a JSON tiddler and parse it. Returns None if not found."""
        tiddler = await self.get_tiddler(recipe, title)
        if tiddler is None:
            return None
        text = tiddler.get("text", "{}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"JSON decode error for tiddler '{title}'")
            return None

    # ──────────────────────────────────────────────────────────────
    # Convenience: get tiddlers by tag
    # ──────────────────────────────────────────────────────────────

    async def get_tiddlers_by_tag(self, recipe: str, tag: str) -> List[Dict[str, Any]]:
        """Get all tiddlers with a specific tag."""
        all_tiddlers = await self.list_tiddlers(recipe)
        return [
            t for t in all_tiddlers
            if tag in t.get("tags", "")
        ]

    # ──────────────────────────────────────────────────────────────
    # Health check
    # ──────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check if MWS is reachable and auth is working."""
        try:
            await self._ensure_auth()
            client = await self._get_client()
            resp = await client.get(
                f"{self.base_url}/",
                headers={"Cookie": self.session_cookie} if self.session_cookie else {},
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None