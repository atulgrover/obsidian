"""
MWS Client — HTTP client for TiddlyWiki MultiWikiServer (MWS).

Handles authentication, wiki (recipe) CRUD, and tiddler CRUD via the MWS API.
Each PDF document maps to its own wiki instance (recipe) in MWS.
"""

from __future__ import annotations

import json
import logging
import subprocess
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

    Usage:
        client = MWSClient("http://mws:8080", "admin", "1234")
        await client.authenticate()
        await client.create_wiki("my-doc")
        await client.put_tiddler("my-doc", "Hello", text="Hello world!", tags="hello test")
    """

    def __init__(self, base_url: str, username: str = "admin", password: str = "1234"):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session_cookie: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ──────────────────────────────────────────────────────────────
    # Authentication
    # ──────────────────────────────────────────────────────────────

    async def authenticate(self) -> None:
        """Authenticate with MWS and store the session cookie.

        Uses a Node.js helper script (mws-login.js) for OPAQUE auth,
        then falls back to simple cookie-based auth if available.
        """
        # Strategy 1: Try Node.js helper for OPAQUE auth
        login_js = Path(__file__).parent.parent / "mws-service" / "mws-login.js"
        if login_js.exists():
            try:
                cookie = await self._authenticate_via_node(str(login_js))
                if cookie:
                    self.session_cookie = cookie
                    logger.info("MWS authentication successful via Node.js helper")
                    return
            except Exception as e:
                logger.warning(f"Node.js MWS auth failed: {e}")

        # Strategy 2: Direct simple auth (for MWS versions that support it)
        try:
            await self._authenticate_direct()
            logger.info("MWS authentication successful via direct auth")
            return
        except Exception as e:
            logger.warning(f"Direct MWS auth failed: {e}")

        # Strategy 3: No auth (for internal/dev setups with auth disabled)
        logger.warning("MWS auth methods failed; proceeding without auth (may fail on write)")
        self.session_cookie = "no-auth"

    async def _authenticate_via_node(self, script_path: str) -> Optional[str]:
        """Use Node.js helper to perform OPAQUE authentication."""
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            "node", script_path, self.base_url, self.username, self.password,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise MWSAuthError(f"Node.js auth helper failed: {stderr.decode()}")
        cookie = stdout.decode().strip()
        return cookie if cookie else None

    async def _authenticate_direct(self) -> None:
        """Try direct authentication against MWS.

        MWS uses OPAQUE protocol (2-phase login). This attempts a simplified
        flow that may work depending on the MWS version and configuration.
        """
        client = await self._get_client()

        # Phase 1: Start login
        resp = await client.post(
            f"{self.base_url}/login/1",
            json={"username": self.username, "password": self.password},
        )
        if resp.status_code == 200:
            login_data = resp.json()

            # Phase 2: Finish login
            resp2 = await client.post(
                f"{self.base_url}/login/2",
                json={
                    "finishLoginRequest": login_data.get("finishLoginRequest", ""),
                    "loginSession": login_data.get("loginSession", ""),
                },
            )
            if resp2.status_code == 200:
                # Extract session cookie from Set-Cookie header
                set_cookie = resp2.headers.get("set-cookie", "")
                if set_cookie:
                    # Parse the cookie value
                    for part in set_cookie.split(";"):
                        part = part.strip()
                        if "=" in part and not part.startswith(("Path", "Domain", "HttpOnly", "Secure", "SameSite")):
                            self.session_cookie = part
                            return

        # Fallback: try simple session-based auth
        resp = await client.post(
            f"{self.base_url}/login",
            json={"username": self.username, "password": self.password},
            headers={"X-Requested-With": "TiddlyWiki"},
        )
        if resp.status_code == 200:
            set_cookie = resp.headers.get("set-cookie", "")
            if set_cookie:
                for part in set_cookie.split(";"):
                    part = part.strip()
                    if "=" in part and not part.startswith(("Path", "Domain", "HttpOnly", "Secure", "SameSite")):
                        self.session_cookie = part
                        return

        raise MWSAuthError("Direct authentication failed")

    async def _ensure_auth(self) -> None:
        """Ensure we have a valid session cookie, re-authenticate if needed."""
        if not self.session_cookie or self.session_cookie == "no-auth":
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
        headers: Optional[Dict[str, str]] = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        """Make an authenticated request to MWS, auto-refreshing session on 401."""
        await self._ensure_auth()

        client = await self._get_client()
        req_headers = {
            "Content-Type": "application/json",
            "X-Requested-With": "TiddlyWiki",
        }
        if self.session_cookie and self.session_cookie != "no-auth":
            req_headers["Cookie"] = self.session_cookie
        if headers:
            req_headers.update(headers)

        resp = await client.request(
            method,
            f"{self.base_url}{path}",
            json=json_data,
            headers=req_headers,
        )

        if resp.status_code == 401 and retry_auth:
            # Session expired; re-authenticate and retry once
            await self.authenticate()
            req_headers["Cookie"] = self.session_cookie
            resp = await client.request(
                method,
                f"{self.base_url}{path}",
                json=json_data,
                headers=req_headers,
            )

        return resp

    # ──────────────────────────────────────────────────────────────
    # Wiki (Recipe) CRUD
    # ──────────────────────────────────────────────────────────────

    async def create_wiki(self, slug: str, description: str = "") -> Dict[str, Any]:
        """Create a new wiki (recipe + bag) in MWS.

        Each PDF document gets its own wiki. The slug becomes the recipe name.

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
                "plugin_names": [],
                "skip_required_plugins": False,
                "skip_core": False,
                "preload_store": False,
                "create_only": True,
            },
        )
        if resp.status_code not in (200, 201, 204):
            # Recipe may already exist — that's OK
            logger.debug(f"Recipe creation returned {resp.status_code}: {resp.text[:200]}")

        logger.info(f"Created wiki: {slug}")
        return {"recipe": slug, "bag": bag_name}

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
        resp = await self._request("POST", "/admin/index_json", json_data={})
        if resp.status_code != 200:
            logger.warning(f"Failed to list wikis: {resp.status_code}")
            return []
        data = resp.json()
        # The index_json endpoint returns a dict with recipe info
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
        payload: Dict[str, Any] = {
            "title": title,
            "text": text,
            "type": tiddler_type,
        }
        if tags:
            payload["tags"] = tags
        if fields:
            payload["fields"] = {k: str(v) for k, v in fields.items()}

        resp = await self._request(
            "PUT",
            f"/recipe/{recipe}/tiddlers/{encoded_title}",
            json_data=payload,
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
        resp = await self._request(
            "PUT",
            f"/recipe/{recipe}/rpc/batch-save",
            json_data={"tiddlers": tiddlers},
        )
        if resp.status_code not in (200, 201, 204):
            # Fallback: save tiddlers one by one
            results = []
            for t in tiddlers:
                title = t.pop("title")
                text = t.pop("text", "")
                tags = t.pop("tags", "")
                fields = t  # remaining keys are custom fields
                result = await self.put_tiddler(recipe, title, text=text, tags=tags, fields=fields)
                results.append(result)
            return results
        try:
            return resp.json()
        except Exception:
            return [{"status": "ok"}]

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
        """Check if MWS is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/")
            return resp.status_code == 200
        except Exception:
            return False