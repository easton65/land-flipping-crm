"""Discovery backends: turn search queries into candidate domains.

Backends implement ``search(query, client) -> list[Candidate]``.

Available:
  * duckduckgo  — keyless HTML scraping (default; polite, rate-limited).
  * serper      — google.serper.dev  (env SERPER_API_KEY).
  * serpapi     — serpapi.com         (env SERPAPI_API_KEY).
  * bing        — Bing Web Search API (env BING_API_KEY).
  * google_cse  — Google Custom Search(env GOOGLE_API_KEY + GOOGLE_CSE_ID).

Plus a listicle harvester that extracts outbound domains from directory/blog
pages returned by any backend — a cheap way to snowball volume.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .core import HttpClient, normalize_domain

_DDG_HREF = re.compile(r'href="(//duckduckgo\.com/l/\?[^"]*uddg=[^"]*)"')
_ANY_HREF = re.compile(r'href=["\'](https?://[^"\'#]+)["\']', re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    domain: str
    url: str
    query: str
    source: str


def _uddg_targets(body: str) -> list[str]:
    out = []
    for m in _DDG_HREF.finditer(body):
        href = html.unescape(m.group(1))
        qs = urllib.parse.urlsplit("https:" + href).query
        params = urllib.parse.parse_qs(qs)
        for target in params.get("uddg", []):
            if "duckduckgo.com" not in target:  # skip ad/redirect chains
                out.append(target)
    return out


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #

def search_duckduckgo(query: str, client: HttpClient) -> list[Candidate]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    status, _, body = client.get(url, max_bytes=800_000)
    if status != 200:
        return []
    text = body.decode("utf-8", "ignore")
    out, seen = [], set()
    for target in _uddg_targets(text):
        dom = normalize_domain(target)
        if dom and dom not in seen:
            seen.add(dom)
            out.append(Candidate(dom, target, query, "duckduckgo"))
    return out


def _from_result_list(items, url_key, query, source) -> list[Candidate]:
    out, seen = [], set()
    for it in items or []:
        link = it.get(url_key) or it.get("link") or it.get("url")
        if not link:
            continue
        dom = normalize_domain(link)
        if dom and dom not in seen:
            seen.add(dom)
            out.append(Candidate(dom, link, query, source))
    return out


def search_serper(query: str, client: HttpClient) -> list[Candidate]:
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        return []
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=json.dumps({"q": query, "num": 100}).encode(),
        headers={"X-API-KEY": key, "Content-Type": "application/json",
                 "User-Agent": client.user_agent},
    )
    try:
        with client._opener.open(req, timeout=client.timeout) as resp:  # noqa: SLF001
            data = json.loads(resp.read(2_000_000).decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return []
    return _from_result_list(data.get("organic"), "link", query, "serper")


def search_serpapi(query: str, client: HttpClient) -> list[Candidate]:
    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        return []
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
        {"q": query, "engine": "google", "num": 100, "api_key": key}
    )
    status, _, data = client.get_json(url)
    if not data:
        return []
    return _from_result_list(data.get("organic_results"), "link", query, "serpapi")


def search_bing(query: str, client: HttpClient) -> list[Candidate]:
    key = os.environ.get("BING_API_KEY")
    if not key:
        return []
    url = "https://api.bing.microsoft.com/v7.0/search?" + urllib.parse.urlencode(
        {"q": query, "count": 50, "responseFilter": "Webpages"}
    )
    status, _, data = client.get_json(
        url, headers={"Ocp-Apim-Subscription-Key": key}
    )
    if not data:
        return []
    items = (data.get("webPages") or {}).get("value")
    return _from_result_list(items, "url", query, "bing")


def search_google_cse(query: str, client: HttpClient) -> list[Candidate]:
    key = os.environ.get("GOOGLE_API_KEY")
    cx = os.environ.get("GOOGLE_CSE_ID")
    if not (key and cx):
        return []
    out: list[Candidate] = []
    for start in (1, 11, 21, 31, 41):  # CSE returns 10 per page, 5 pages max here
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(
            {"key": key, "cx": cx, "q": query, "num": 10, "start": start}
        )
        status, _, data = client.get_json(url)
        if not data:
            break
        out.extend(_from_result_list(data.get("items"), "link", query, "google_cse"))
        if len(data.get("items") or []) < 10:
            break
    return out


BACKENDS = {
    "duckduckgo": search_duckduckgo,
    "serper": search_serper,
    "serpapi": search_serpapi,
    "bing": search_bing,
    "google_cse": search_google_cse,
}


# --------------------------------------------------------------------------- #
# Listicle harvesting
# --------------------------------------------------------------------------- #

_LISTICLE_HINTS = ("best", "top", "list", "guide", "review", "vs", "brands",
                   "retailers", "stores", "shops", "where to buy")


def looks_like_listicle(cand: Candidate) -> bool:
    u = cand.url.lower()
    return any(h in u for h in _LISTICLE_HINTS)


def harvest_outbound_domains(url: str, client: HttpClient) -> list[str]:
    """Fetch a page and return registrable domains it links out to."""
    status, _, body = client.get(url, max_bytes=600_000)
    if status != 200:
        return []
    text = body.decode("utf-8", "ignore")
    src = normalize_domain(url)
    seen, out = set(), []
    for m in _ANY_HREF.finditer(text):
        dom = normalize_domain(m.group(1))
        if dom and dom != src and dom not in seen:
            seen.add(dom)
            out.append(dom)
    return out
