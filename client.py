"""
Async Intigriti researcher API client.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://api.intigriti.com/external/researcher"


class NotAuthenticatedError(Exception):
    pass


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class IntigritiClient:
    def __init__(self, token: str):
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "intigriti-mcp/0.1",
            },
            timeout=30.0,
        )

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._http.get(path, params=params)
        if resp.status_code == 401:
            raise NotAuthenticatedError("Token expired, invalid, or missing required permissions.")
        if resp.status_code == 403:
            raise ForbiddenError(f"Access forbidden: {path}")
        if resp.status_code == 404:
            raise NotFoundError(f"Resource not found: {path}")
        resp.raise_for_status()
        return resp.json()

    async def get_records(
        self,
        path: str,
        extra_params: dict[str, Any] | None = None,
        limit: int = 500,
        all_pages: bool = True,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = int((extra_params or {}).pop("offset", 0) or 0)
        limit = max(1, min(int(limit or 500), 500))

        while True:
            params: dict[str, Any] = {"limit": limit, "offset": offset}
            if extra_params:
                params.update({k: v for k, v in extra_params.items() if v is not None})
            data = await self.get(path, params=params)
            page_records = data.get("records", [])
            if not isinstance(page_records, list) or not page_records:
                break
            records.extend(page_records)
            max_count = int(data.get("maxCount", len(records)) or len(records))
            if not all_pages or len(records) >= max_count:
                break
            offset += len(page_records)
        return records

    async def get_programs(
        self,
        status_id: int | None = None,
        type_id: int | None = None,
        following: bool | None = None,
        all_pages: bool = True,
    ) -> list[dict[str, Any]]:
        return await self.get_records(
            "/v1/programs",
            {
                "statusId": status_id,
                "typeId": type_id,
                "following": following,
            },
            all_pages=all_pages,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "IntigritiClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
