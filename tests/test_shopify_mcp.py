# tests/test_shopify_mcp.py
from unittest.mock import patch, MagicMock
import pytest
from app.services.shopify_mcp import (
    ShopifyMCPClient,
    ProductNotFoundError,
    BlogNotFoundError,
    ShopifyConnectionError,
)

LANG_CODES = ["fr", "de", "es", "it", "nl", "pl", "sl", "pt"]
BASE = "https://legendary-parts.com"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SHOPIFY_ADMIN_API_TOKEN", "test-token")
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "legendary-parts.myshopify.com")
    monkeypatch.setenv("SHOPIFY_STORE_URL", "https://legendary-parts.com")
    return ShopifyMCPClient()


def _mock_graphql(client, response_data):
    """Helper: patch client._request to return response_data."""
    client._request = MagicMock(return_value=response_data)


def test_get_product_urls_returns_all_eight_langs(client):
    # _request returns only the product handle; URLs are built locally
    _mock_graphql(client, {
        "data": {"products": {"nodes": [{"handle": "belt-guard-60367-04a"}]}}
    })
    result = client.get_product_urls_by_oem("60367-04A")
    assert set(result.keys()) == set(LANG_CODES)
    assert result["fr"] == f"{BASE}/fr/products/belt-guard-60367-04a"
    assert result["de"] == f"{BASE}/de/products/belt-guard-60367-04a"


def test_get_product_urls_raises_not_found(client):
    _mock_graphql(client, {"data": {"products": {"nodes": []}}})
    with pytest.raises(ProductNotFoundError):
        client.get_product_urls_by_oem("UNKNOWN-OEM")


def test_get_blog_urls_returns_all_eight_langs(client):
    # _request returns article handle + blog handle; URLs are built locally
    _mock_graphql(client, {
        "data": {
            "articles": {
                "nodes": [{
                    "handle": "best-harley-batteries",
                    "blog": {"handle": "news"},
                }]
            }
        }
    })
    result = client.get_blog_urls_by_slug("best-harley-batteries")
    assert set(result.keys()) == set(LANG_CODES)
    assert result["fr"] == f"{BASE}/fr/blogs/news/best-harley-batteries"
    assert result["de"] == f"{BASE}/de/blogs/news/best-harley-batteries"


def test_get_blog_urls_raises_not_found(client):
    _mock_graphql(client, {"data": {"articles": {"nodes": []}}})
    with pytest.raises(BlogNotFoundError):
        client.get_blog_urls_by_slug("unknown-slug")


def test_401_raises_immediately_with_message(client):
    import requests
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_resp)
    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="token invalid or expired"):
            client.get_product_urls_by_oem("ANY-OEM")


def test_network_error_retries_then_raises(client):
    import requests
    with patch("requests.post", side_effect=requests.exceptions.ConnectionError("refused")):
        with patch("time.sleep"):  # don't actually sleep
            with pytest.raises(ShopifyConnectionError, match="unreachable"):
                client.get_product_urls_by_oem("ANY-OEM")


def test_missing_env_raises_on_init(monkeypatch):
    monkeypatch.delenv("SHOPIFY_ADMIN_API_TOKEN", raising=False)
    monkeypatch.delenv("SHOPIFY_STORE_DOMAIN", raising=False)
    monkeypatch.delenv("SHOPIFY_STORE_URL", raising=False)
    with pytest.raises(RuntimeError, match="SHOPIFY_ADMIN_API_TOKEN"):
        ShopifyMCPClient()
