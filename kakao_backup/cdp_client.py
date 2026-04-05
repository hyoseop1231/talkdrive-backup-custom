"""Chrome DevTools Protocol (CDP) client for Kakao TalkCloud API.

Connects to a Chrome instance with remote debugging enabled, finds the
talkcloud.kakao.com tab, and executes API calls through the browser session
so that cookies are automatically included.
"""

import asyncio
import json
import logging

import aiohttp
import websockets

from kakao_backup.config import API_BASE, CHROME_DEBUG_PORT

logger = logging.getLogger(__name__)


class TalkCloudClient:
    """CDP-based TalkCloud API client."""

    def __init__(self, debug_port: int = CHROME_DEBUG_PORT):
        self.debug_port = debug_port
        self.debug_url = f"http://localhost:{debug_port}"
        self.ws = None
        self.ws_url = None
        self._msg_id = 0
        self._axios_loaded = False

    async def connect(self):
        """Connect to Chrome debugging port and find the talkcloud tab."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.debug_url}/json") as resp:
                tabs = await resp.json()

        # Prefer talkcloud.kakao.com tab
        target_tab = None
        for tab in tabs:
            url = tab.get("url", "")
            if "talkcloud.kakao.com" in url or "drawer" in url:
                target_tab = tab
                break

        if not target_tab:
            for tab in tabs:
                if tab.get("type") == "page" and "webSocketDebuggerUrl" in tab:
                    target_tab = tab
                    break

        if not target_tab:
            raise RuntimeError(
                f"No Chrome tab found. "
                f"Ensure Chrome is running with --remote-debugging-port={self.debug_port}"
            )

        self.ws_url = target_tab["webSocketDebuggerUrl"]
        self.ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        logger.info("Connected to: %s (%s)", target_tab.get("title", "?"), target_tab.get("url"))
        return self

    async def close(self):
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def _send_cdp(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and wait for the matching response."""
        self._msg_id += 1
        msg: dict = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        await self.ws.send(json.dumps(msg))

        while True:
            response = json.loads(await self.ws.recv())
            if response.get("id") == self._msg_id:
                return response

    async def _evaluate(self, expression: str):
        """Execute JavaScript in the browser context."""
        result = await self._send_cdp("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })

        if "error" in result:
            raise RuntimeError(f"CDP error: {result['error']}")

        res = result.get("result", {}).get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError(f"JS error: {res.get('description', 'Unknown')}")

        return res.get("value")

    async def _ensure_axios(self):
        """Load the axios library once."""
        if self._axios_loaded:
            return
        await self._evaluate("""
            (async () => {
                if (typeof window.__axios === 'undefined') {
                    const mod = await import('https://cdn.jsdelivr.net/npm/axios@1.7.9/+esm');
                    window.__axios = mod.default;
                }
                return 'axios loaded';
            })()
        """)
        self._axios_loaded = True

    async def get(self, path: str, params: dict | None = None) -> dict:
        """Perform a GET request via the browser session."""
        await self._ensure_axios()
        params_js = json.dumps(params) if params else "{}"
        url = f"{API_BASE}{path}"
        return await self._evaluate(f"""
            (async () => {{
                const resp = await window.__axios.get('{url}', {{
                    params: {params_js},
                    headers: {{"Accept": "application/json+javascript"}},
                    withCredentials: true
                }});
                return resp.data;
            }})()
        """)

    async def post(self, path: str, data: dict | None = None) -> dict:
        """Perform a POST request via the browser session."""
        await self._ensure_axios()
        data_js = json.dumps(data) if data else "{}"
        url = f"{API_BASE}{path}"
        return await self._evaluate(f"""
            (async () => {{
                const resp = await window.__axios.post('{url}', {data_js}, {{
                    headers: {{
                        "Accept": "application/json+javascript",
                        "Content-Type": "application/json"
                    }},
                    withCredentials: true
                }});
                return resp.data;
            }})()
        """)

    async def get_paginated(
        self,
        path: str,
        params: dict | None = None,
        fetch_count: int = 100,
        direction: str = "DESC",
    ) -> list:
        """Fetch all pages of a paginated endpoint.

        Returns:
            Combined list of all items across pages.
        """
        all_items: list = []
        base_params = dict(params or {})
        base_params.update({"fetchCount": fetch_count, "direction": direction})

        cursor = None
        page = 0

        while True:
            page += 1
            req_params = {**base_params}
            if cursor:
                req_params["cursor"] = cursor

            result = await self.get(path, req_params)
            items = result.get("items", [])
            all_items.extend(items)

            total = result.get("totalCount", 0)
            cursor = result.get("cursor")

            logger.info("Page %d: +%d items (total: %d/%d)", page, len(items), len(all_items), total)

            if not items or not cursor or len(all_items) >= total:
                break

            await asyncio.sleep(0.2)

        return all_items

    # --- Convenience methods ---

    async def get_user_info(self) -> dict:
        return await self.get("/user/info")

    async def get_friends(self) -> dict:
        return await self.get("/friend/list")

    async def get_chat_list(self, vertical_type: str = "MEDIA") -> dict:
        return await self.get("/chat/list", {"verticalType": vertical_type})

    async def get_backup_info(self) -> dict:
        return await self.get("/backup/info")

    async def get_media_list(self, **kwargs) -> dict:
        params = {
            "verticalType": "MEDIA",
            "fetchCount": 100,
            "joined": "true",
            "direction": "DESC",
            **kwargs,
        }
        return await self.get("/mediaFile/list", params)

    async def get_all_media(self) -> list:
        """Fetch the complete media file list with pagination."""
        return await self.get_paginated(
            "/mediaFile/list",
            {"verticalType": "MEDIA", "joined": "true"},
        )

    async def get_media_tags(self) -> dict:
        return await self.get("/mediaFile/tag/all")

    async def get_labels(self, vertical_type: str = "MEDIA") -> dict:
        return await self.get("/label/list", {"verticalType": vertical_type})

    async def get_folders(self) -> dict:
        return await self.get("/folder/list", {
            "type": "USER", "verticalType": "MEDIA", "fetchCount": 100,
        })

    async def get_cloud_folders(self) -> dict:
        return await self.get("/v2/cloud/list", {
            "root": "true", "type": "FOLDER", "fetchCount": 100,
            "direction": "ASC", "sortProperty": "NAME",
        })

    async def get_contact_snapshots(self) -> dict:
        return await self.get("/contactSnapshot/list", {"fetchCount": 50})

    async def get_contacts(self, snapshot_id: str) -> dict:
        return await self.get("/contact/list", {
            "snapshotId": snapshot_id, "fetchCount": 100,
        })

    async def get_contact_snapshot_detail(self, snapshot_id: str) -> dict:
        return await self.get(f"/contactSnapshot/{snapshot_id}")

    async def get_friend_latest_media(self) -> dict:
        return await self.get("/mediaFile/friend/latest", {"verticalType": "MEDIA"})

    async def get_chatbots(self) -> dict:
        return await self.get("/chatbot/list")

    async def get_notice_cards(self) -> dict:
        return await self.get("/v3/noticeCard/list")
