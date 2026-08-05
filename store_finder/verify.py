"""Verify a domain's e-commerce platform (Shopify / WooCommerce) and niche fit.

Detection uses each platform's public product API first (which doubles as the
niche-matching data source), then falls back to response headers and homepage
HTML markers. Store fronts that merely return a JS lander are rejected because
the API responses must parse as genuine product collections.
"""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field

from .core import HttpClient
from .niche import Niche

# --------------------------------------------------------------------------- #
# Fingerprints
# --------------------------------------------------------------------------- #
_SHOPIFY_HEADERS = (
    "x-shopify-stage", "x-shopid", "x-shardid",
    "x-sorting-hat-shopid", "x-sorting-hat-podid",
)
_SHOPIFY_HTML_MARKERS = ("cdn.shopify.com", "shopify.shop", "myshopify.com",
                         "shopify.theme", "/cdn/shop/")
_WOO_HTML_MARKERS = ("woocommerce", "/wp-content/plugins/woocommerce",
                     "wc-block", "wc_add_to_cart_params", "wp-content/themes")
# The strongest Woo signal: the WooCommerce plugin path / body classes.
_WOO_STRONG_MARKERS = ("woocommerce", "/wp-content/plugins/woocommerce",
                       "wc-block-components", "wc_add_to_cart_params")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _visible_text(htmltext: str) -> str:
    """Lowercased visible text with scripts/styles/tags stripped."""
    t = _SCRIPT_STYLE_RE.sub(" ", htmltext or "")
    t = _TAG_RE.sub(" ", t)
    return html.unescape(t).lower()


def _title(htmltext: str) -> str:
    m = _TITLE_RE.search(htmltext)
    if not m:
        return ""
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()[:200]


@dataclass
class StoreResult:
    domain: str
    platform: str = ""            # "shopify" | "woocommerce" | ""
    is_store: bool = False
    evidence: str = ""
    in_niche: bool = False
    name: str = ""
    homepage: str = ""
    matched_terms: list[str] = field(default_factory=list)
    products_sampled: int = 0
    match_hits: int = 0
    source: str = ""
    query: str = ""


# --------------------------------------------------------------------------- #
# Product-collection fetchers (also used for niche matching)
# --------------------------------------------------------------------------- #

def _get_json_retry(client: HttpClient, url: str):
    """GET JSON with retry on rate-limit / transient failures."""
    data = None
    for attempt in range(3):
        status, _, data = client.get_json(url)
        if data is not None:
            return data
        if status in (0, 429, 430, 503):
            time.sleep(0.75 * (attempt + 1))
            continue
        break
    return data


def _shopify_products(domain: str, client: HttpClient, page: int):
    data = _get_json_retry(
        client, f"https://{domain}/products.json?limit=250&page={page}")
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        return data["products"], 250
    return None, 250


def _shopify_blob(p: dict) -> str:
    blob = " ".join(str(p.get(k, "")) for k in ("title", "product_type", "vendor"))
    tags = p.get("tags")
    if isinstance(tags, list):
        blob += " " + " ".join(str(t) for t in tags)
    elif isinstance(tags, str):
        blob += " " + tags
    return blob


def _woo_products(domain: str, client: HttpClient, page: int):
    for base in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
        data = _get_json_retry(
            client, f"https://{domain}{base}?per_page=100&page={page}")
        if isinstance(data, list):
            return data, 100
    return None, 100


def _woo_blob(p: dict) -> str:
    parts = [str(p.get("name", "")), str(p.get("slug", "")),
             str(p.get("short_description", ""))]
    for cat in p.get("categories") or []:
        if isinstance(cat, dict):
            parts.append(str(cat.get("name", "")))
    for tag in p.get("tags") or []:
        if isinstance(tag, dict):
            parts.append(str(tag.get("name", "")))
    return " ".join(parts)


_FETCHERS = {
    "shopify": (_shopify_products, _shopify_blob),
    "woocommerce": (_woo_products, _woo_blob),
}


# --------------------------------------------------------------------------- #
# Platform detection
# --------------------------------------------------------------------------- #

def detect_platform(
    domain: str, client: HttpClient, platforms: list[str],
) -> tuple[str, str, str]:
    """Return (platform, evidence, homepage_html). platform='' if none matched."""
    base = f"https://{domain}"

    # 1) API probes (also proves the store is live and reachable).
    if "shopify" in platforms:
        data = _get_json_retry(client, f"{base}/products.json?limit=1")
        if isinstance(data, dict) and isinstance(data.get("products"), list):
            return "shopify", "products.json", ""
    if "woocommerce" in platforms:
        for p in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
            data = _get_json_retry(client, f"{base}{p}?per_page=1")
            if isinstance(data, list):
                return "woocommerce", "store-api", ""

    # 2) Homepage headers / HTML markers (single fetch, checked for both).
    status, headers, body = client.get(base, max_bytes=250_000)
    if status == 0:
        return "", "unreachable", ""
    text = body.decode("utf-8", "ignore")
    low = text.lower()

    if "shopify" in platforms:
        if any(h in headers for h in _SHOPIFY_HEADERS):
            return "shopify", "header", text
        if any(mk in low for mk in _SHOPIFY_HTML_MARKERS):
            return "shopify", "html-marker", text
    if "woocommerce" in platforms:
        link = headers.get("link", "").lower()
        if any(mk in low for mk in _WOO_STRONG_MARKERS) or "wp-json" in link:
            if any(mk in low for mk in _WOO_HTML_MARKERS):
                return "woocommerce", "html-marker", text
    return "", "no-marker", text


# --------------------------------------------------------------------------- #
# Niche matching
# --------------------------------------------------------------------------- #

def _match_products(products: list, terms: list[str], blob_fn) -> tuple[int, set[str]]:
    hits = 0
    matched: set[str] = set()
    for p in products:
        if not isinstance(p, dict):
            continue
        blob = blob_fn(p).lower()
        found = [t for t in terms if t in blob]
        if found:
            hits += 1
            matched.update(found)
    return hits, matched


def check_niche(
    domain: str, platform: str, niche: Niche, client: HttpClient,
    homepage_html: str = "", max_pages: int = 3, min_hits: int = 1,
) -> tuple[bool, list[str], int, int]:
    """Return (in_niche, matched_terms, match_hits, products_sampled)."""
    terms = niche.match_terms
    fetch, blob_fn = _FETCHERS[platform]
    total_hits, sampled = 0, 0
    matched: set[str] = set()

    for page in range(1, max_pages + 1):
        products, page_size = fetch(domain, client, page)
        if not products:
            break
        sampled += len(products)
        h, m = _match_products(products, terms, blob_fn)
        total_hits += h
        matched.update(m)
        if len(products) < page_size:
            break

    # Fallback: match homepage text when the product API is blocked/empty.
    if sampled == 0:
        text = homepage_html
        if not text:
            _, _, body = client.get(f"https://{domain}", max_bytes=250_000)
            text = body.decode("utf-8", "ignore")
        low = _visible_text(text)
        for t in terms:
            if t in low:
                matched.add(t)
                total_hits += 1

    in_niche = total_hits >= min_hits and bool(matched)
    return in_niche, sorted(matched), total_hits, sampled


def verify_store(
    domain: str, niche: Niche, client: HttpClient, *,
    platforms: list[str] | None = None,
    source: str = "", query: str = "", require_niche: bool = True,
    min_hits: int = 1,
) -> StoreResult:
    platforms = platforms or ["shopify", "woocommerce"]
    res = StoreResult(domain=domain, source=source, query=query)

    platform, evidence, homepage_html = detect_platform(domain, client, platforms)
    res.platform = platform
    res.evidence = evidence
    res.is_store = bool(platform)
    if not platform:
        return res

    if homepage_html:
        res.name = _title(homepage_html)
    if not res.name:
        _, _, body = client.get(f"https://{domain}", max_bytes=120_000)
        res.name = _title(body.decode("utf-8", "ignore"))
    res.homepage = f"https://{domain}"

    in_niche, matched, hits, sampled = check_niche(
        domain, platform, niche, client, homepage_html=homepage_html,
        min_hits=min_hits,
    )
    res.matched_terms = matched
    res.match_hits = hits
    res.products_sampled = sampled
    # In --any-store mode every detected store is kept regardless of niche fit.
    res.in_niche = in_niche or not require_niche
    return res
