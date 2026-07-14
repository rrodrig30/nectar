"""USDA FoodData Central client (bulk + targeted).

Thin HTTP wrapper only. This module never computes or asserts a nutrient value; it fetches
candidate foods and raw FDC records for the matcher (`resolution/matcher.py`) to rank and for
downstream nutrition code to read verbatim, canonical-unit facts from. See ../../docs/SDD.md
Section 3.3 and ../../docs/PDD.md Section 1 (resolution/ layout). Invariants in ../../CLAUDE.md
apply: models normalize strings, they never assert composition; this client performs no ranking.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Final

import requests

FDC_BASE_URL: Final[str] = "https://api.nal.usda.gov/fdc/v1"
DEFAULT_TIMEOUT_S: Final[float] = 10.0


class FdcConfigError(RuntimeError):
    """Raised when the FDC client is misconfigured, e.g. no API key in the environment."""


class FdcRequestError(RuntimeError):
    """Raised when a request to the FDC API fails or returns an unexpected shape."""


@dataclass(frozen=True)
class FdcCandidate:
    """One search result returned by FDC, prior to any ranking."""

    fdc_id: int
    description: str
    data_type: str
    score: float


def _require_api_key(api_key: str | None) -> str:
    key = api_key if api_key is not None else os.environ.get("FDC_API_KEY")
    if not key:
        raise FdcConfigError(
            "FDC_API_KEY is not set. Provide it via the environment or the FdcClient "
            "constructor; see nutriscrape/.env.example."
        )
    return key


class FdcClient:
    """Thin HTTP client over the USDA FoodData Central API.

    Keeps I/O isolated to this module per the resolution/ boundary: no ranking, no scoring,
    no nutrient interpretation. `search` returns untyped candidates for `matcher.rank_candidates`
    to score; `food` returns the raw FDC record for downstream normalization code to parse.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = FDC_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = _require_api_key(api_key)
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._session = session if session is not None else requests.Session()

    def search(self, query: str, page_size: int = 25) -> list[FdcCandidate]:
        """Search FDC for candidate foods matching `query`. No ranking is applied here."""
        payload: dict[str, Any] = {
            "query": query,
            "pageSize": page_size,
            "api_key": self._api_key,
        }
        try:
            response = self._session.get(
                f"{self._base_url}/foods/search", params=payload, timeout=self._timeout_s
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FdcRequestError(f"FDC search failed for query '{query}': {exc}") from exc

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise FdcRequestError(f"FDC search returned non-JSON for query '{query}'") from exc

        foods = body.get("foods", [])
        if not isinstance(foods, list):
            raise FdcRequestError(f"FDC search returned unexpected shape for query '{query}'")

        candidates: list[FdcCandidate] = []
        for item in foods:
            fdc_id = item.get("fdcId")
            description = item.get("description")
            data_type = item.get("dataType")
            if fdc_id is None or description is None or data_type is None:
                continue
            candidates.append(
                FdcCandidate(
                    fdc_id=int(fdc_id),
                    description=str(description),
                    data_type=str(data_type),
                    score=float(item.get("score", 0.0)),
                )
            )
        return candidates

    def food(self, fdc_id: int) -> dict[str, Any]:
        """Fetch the full FDC record for a resolved food id. Raw pass-through, no interpretation."""
        payload: dict[str, Any] = {"api_key": self._api_key}
        try:
            response = self._session.get(
                f"{self._base_url}/food/{fdc_id}", params=payload, timeout=self._timeout_s
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FdcRequestError(f"FDC food lookup failed for fdc_id {fdc_id}: {exc}") from exc

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise FdcRequestError(f"FDC food lookup returned non-JSON for fdc_id {fdc_id}") from exc

        return body
