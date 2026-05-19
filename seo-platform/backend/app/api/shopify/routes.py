"""
Shopify integration routes: product listing, SEO field updates, shop info.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.middleware.auth import require_admin, get_current_user
from app.models import User
from app.services.shopify import get_shopify_client, ShopifyClient

router = APIRouter(prefix="/api/shopify", tags=["shopify"])


def _client() -> ShopifyClient:
    try:
        return get_shopify_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ── Shop ──

@router.get("/shop")
async def shop_info(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return basic info about the connected Shopify store."""
    return await _client().get_shop()


# ── Products ──

@router.get("/products")
async def list_products(
    limit: int = Query(50, ge=1, le=250),
    page_info: str | None = Query(None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List products from Shopify (cursor-paginated)."""
    return await _client().list_products(limit=limit, page_info=page_info)


@router.get("/products/{product_id}")
async def get_product(
    product_id: int,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await _client().get_product(product_id)


class SeoUpdate(BaseModel):
    seo_title: str
    seo_description: str


@router.put("/products/{product_id}/seo")
async def update_product_seo(
    product_id: int,
    body: SeoUpdate,
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Push SEO title and meta-description back to Shopify (admin only)."""
    return await _client().update_product_seo(
        product_id=product_id,
        seo_title=body.seo_title,
        seo_description=body.seo_description,
    )
