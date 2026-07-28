"""Verify that a domain is a Shopify store and that it sells in the niche."""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field

from .core import HttpClient
from .niche import Niche

_SHOPIFY_HEADERS = (
    "x-shopify-stage", "x-shopid", "x-shardid",
    "x-sorting-hat-shopid", "x-sorting-hat-podid",
)
_SHOPIFY_HTML_MARKERS = ("cdn.shopify.com", "shopify.shop", "myshopify.com",
                         "shopify.theme", "/cdn/shop/")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _visible_text(htmltext: str) -> str:
    """Lowercased visible text with scripts/styles/tags stripped."""
    t = _SCRIPT_STYLE_RE.sub(" ", htmltext or "")
    t = _TAG_RE.sub(" ", t)
    return html.unescape(t).lower()


@dataclass
class StoreResult:
    domain: str
    is_shopify: bool = False
    shopify_evidence: str = ""
    in_niche: bool = False
    name: str = ""
    homepage: str = ""
    matched_terms: list[str] = field(default_factory=list)
    products_sampled: int = 0
    match_hits: int = 0
    source: str = ""
    query: str = ""


def _title(htmltext: str) -> str:
    m = _TITLE_RE.search(htmltext)
    if not m:
        return ""
    t = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
    return t[:200]


def detect_shopify(domain: str, client: HttpClient) -> tuple[bool, str, str]:
    """Return (is_shopify, evidence, homepage_html)."""
    base = f"https://{domain}"

    # 1) products.json must be genuine JSON containing a 'products' array.
    status, headers, data = client.get_json(f"{base}/products.json?limit=1")
    if data and isinstance(data, dict) and isinstance(data.get("products"), list):
        return True, "products.json", ""

    # 2) homepage headers / HTML markers.
    status, headers, body = client.get(base, max_bytes=250_000)
    if status == 0:
        return False, "unreachable", ""
    if any(h in headers for h in _SHOPIFY_HEADERS):
        return True, "header", body.decode("utf-8", "ignore")
    text = body.decode("utf-8", "ignore")
    low = text.lower()
    if any(mk in low for mk in _SHOPIFY_HTML_MARKERS):
        return True, "html-marker", text
    return False, "no-marker", text


def _match_products(niche: Niche, products: list, terms: list[str]) -> tuple[int, set[str]]:
    hits = 0
    matched: set[str] = set()
    for p in products:
        blob = " ".join(str(p.get(k, "")) for k in ("title", "product_type", "vendor"))
        tags = p.get("tags")
        if isinstance(tags, list):
            blob += " " + " ".join(str(t) for t in tags)
        elif isinstance(tags, str):
            blob += " " + tags
        blob = blob.lower()
        found = [t for t in terms if t in blob]
        if found:
            hits += 1
            matched.update(found)
    return hits, matched


def check_niche(
    domain: str, niche: Niche, client: HttpClient, homepage_html: str = "",
    max_pages: int = 2, min_hits: int = 1,
) -> tuple[bool, list[str], int, int]:
    """Return (in_niche, matched_terms, match_hits, products_sampled)."""
    terms = niche.match_terms
    total_hits = 0
    sampled = 0
    matched: set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"https://{domain}/products.json?limit=250&page={page}"
        data = None
        # Shopify rate-limits rapid products.json hits (HTTP 430/503); retry.
        for attempt in range(3):
            status, headers, data = client.get_json(url)
            if data is not None:
                break
            if status in (0, 429, 430, 503):
                time.sleep(0.75 * (attempt + 1))
                continue
            break
        if not data or not isinstance(data.get("products"), list):
            break
        products = data["products"]
        if not products:
            break
        sampled += len(products)
        h, m = _match_products(niche, products, terms)
        total_hits += h
        matched.update(m)
        if len(products) < 250:
            break

    # Fallback: match homepage/collections text when products.json is blocked.
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
    source: str = "", query: str = "", require_niche: bool = True,
    min_hits: int = 1,
) -> StoreResult:
    res = StoreResult(domain=domain, source=source, query=query)
    is_shop, evidence, homepage_html = detect_shopify(domain, client)
    res.is_shopify = is_shop
    res.shopify_evidence = evidence
    if not is_shop:
        return res

    if homepage_html:
        res.name = _title(homepage_html)
    if not res.name:
        _, _, body = client.get(f"https://{domain}", max_bytes=120_000)
        res.name = _title(body.decode("utf-8", "ignore"))
    res.homepage = f"https://{domain}"

    in_niche, matched, hits, sampled = check_niche(
        domain, niche, client, homepage_html=homepage_html, min_hits=min_hits
    )
    res.in_niche = in_niche
    res.matched_terms = matched
    res.match_hits = hits
    res.products_sampled = sampled
    return res
