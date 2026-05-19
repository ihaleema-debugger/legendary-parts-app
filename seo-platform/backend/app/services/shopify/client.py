"""
Shopify Admin REST API client using a permanent access token.
"""

from typing import Any

import httpx

from app.config import get_settings

SHOPIFY_API_VERSION = "2024-04"


class ShopifyClient:
    def __init__(self, store: str, access_token: str) -> None:
        self._base = f"https://{store}/admin/api/{SHOPIFY_API_VERSION}"
        self._headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self._base}{path}",
                headers=self._headers,
                params=params,
            )
            r.raise_for_status()
            return r.json()

    async def _put(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.put(
                f"{self._base}{path}",
                headers=self._headers,
                json=body,
            )
            r.raise_for_status()
            return r.json()

    # ── Products ──

    async def list_products(
        self,
        limit: int = 50,
        page_info: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"limit": min(limit, 250)}
        if page_info:
            params["page_info"] = page_info
        return await self._get("/products.json", params)

    async def get_product(self, product_id: int) -> dict:
        return await self._get(f"/products/{product_id}.json")

    async def update_product_seo(
        self,
        product_id: int,
        seo_title: str,
        seo_description: str,
    ) -> dict:
        body = {
            "product": {
                "id": product_id,
                "metafields_global_title_tag": seo_title,
                "metafields_global_description_tag": seo_description,
            }
        }
        return await self._put(f"/products/{product_id}.json", body)

    # ── Shop info ──

    async def get_shop(self) -> dict:
        return await self._get("/shop.json")


def get_shopify_client() -> ShopifyClient:
    s = get_settings()
    if not s.shopify_store or not s.shopify_access_token:
        raise RuntimeError(
            "Shopify is not configured. Set SHOPIFY_STORE and SHOPIFY_ACCESS_TOKEN."
        )
    return ShopifyClient(store=s.shopify_store, access_token=s.shopify_access_token)
