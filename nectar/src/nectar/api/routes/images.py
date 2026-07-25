"""GET /dish/image - an AI-generated illustration of a dish (PNG), cached on disk.

The image is a synthetic illustration for presentation, clearly labeled as such in the UI; it is
never a photograph of the actual prepared recipe and never a source of any nutrient or clinical
value. The backend is config-driven and optional: with none configured the endpoint returns 503 and
the UI reports the feature as unavailable, rather than faking an image (../../CLAUDE.md, rules.txt).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from nectar.api.deps import get_contract_client
from nectar.common.contract_client import ContractClient
from nectar.images.backends import ImageBackendError, backend_from_env, prompt_for_dish

router = APIRouter()

_ONE_YEAR = "public, max-age=31536000, immutable"


def _cache_path(dish_id: str) -> Path:
    cache_dir = Path(os.environ.get("IMAGE_CACHE_DIR") or "/tmp/nectar-images")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{hashlib.sha1(dish_id.encode()).hexdigest()}.png"


@router.get("/images/status")
def get_image_status() -> dict[str, bool]:
    """Whether image generation is configured, so the UI shows the control only when it will work."""
    return {"available": backend_from_env() is not None}


@router.get(
    "/dish/image",
    responses={200: {"content": {"image/png": {}}}},
    response_class=Response,
)
def get_dish_image(
    dish_id: str = Query(min_length=1, description="Dish id to illustrate"),
    client: ContractClient = Depends(get_contract_client),
) -> Response:
    """The dish's AI-generated illustration as PNG, generated once and cached on disk. 503 when no
    image backend is configured; 404 for an unknown dish; 502 when the image backend errors."""
    path = _cache_path(dish_id)
    if path.is_file():
        return Response(content=path.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": _ONE_YEAR})
    backend = backend_from_env()
    if backend is None:
        raise HTTPException(
            status_code=503, detail="image generation is not configured on this server"
        )
    name = client.dish_name(dish_id)
    if name is None:
        raise HTTPException(status_code=404, detail=f"no dish {dish_id!r}")
    try:
        png = backend.generate(prompt_for_dish(name))
    except ImageBackendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    path.write_bytes(png)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": _ONE_YEAR})
