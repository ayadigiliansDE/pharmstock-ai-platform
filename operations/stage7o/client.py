"""HTTP-only Stage 7M client for Stage 7O."""

from __future__ import annotations

import os
from typing import Any

import httpx

from pharmstock.onprem.stage7o import DEFAULT_STAGE7M_BASE_URL


class Stage7MClientError(RuntimeError):
    """Raised when the governed Stage 7M boundary cannot satisfy a request."""


class Stage7MClient:
    """Read-only service client.

    Stage 7O must never connect to PostgreSQL directly. All operational
    information is obtained through governed Stage 7M GET endpoints.
    """

    def __init__(self) -> None:
        base_url = os.getenv(
            "PHARMSTOCK_STAGE7O_STAGE7M_BASE_URL",
            DEFAULT_STAGE7M_BASE_URL,
        ).strip()

        self._api_key = os.getenv(
            "PHARMSTOCK_STAGE7O_STAGE7M_API_KEY",
            "",
        ).strip()

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=5.0,
                read=15.0,
                write=5.0,
                pool=5.0,
            ),
            follow_redirects=False,
            headers={
                "User-Agent": "pharmstock-stage7o-assistant/0.39.0",
            },
        )

    @property
    def api_key_configured(self) -> bool:
        return bool(self._api_key)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}

        if authenticated:
            if not self._api_key:
                raise Stage7MClientError(
                    "Stage 7M service API key is not configured"
                )

            headers["X-PharmStock-Api-Key"] = self._api_key

        try:
            response = await self._client.get(
                path,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise Stage7MClientError(
                "Stage 7M returned HTTP "
                f"{exc.response.status_code} for GET {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise Stage7MClientError(
                f"Stage 7M request failed for GET {path}: {exc}"
            ) from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise Stage7MClientError(
                f"Stage 7M returned a non-object payload for GET {path}"
            )

        return payload

    async def health(self) -> dict[str, Any]:
        return await self._get(
            "/health",
            authenticated=False,
        )

    async def meta(self) -> dict[str, Any]:
        return await self._get("/v1/meta")

    async def inventory(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/assistant/inventory",
            params=params,
        )

    async def ml_signals(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/assistant/ml-signals",
            params=params,
        )

    async def demand(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/assistant/demand",
            params=params,
        )

    async def suppliers(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/assistant/suppliers",
            params=params,
        )

    async def cases(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/cases",
            params=params,
        )
