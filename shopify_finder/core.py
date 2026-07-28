"""Core utilities: HTTP client, rate limiting, URL/domain helpers, logging.

Standard-library only. Works both on a normal machine and behind an
authenticating proxy with a custom CA bundle (as used by some sandboxes).
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

LOG = logging.getLogger("shopify_finder")

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# Multi-part public suffixes we care about for registrable-domain extraction.
# Not exhaustive, but covers the common ones seen in e-commerce.
_MULTI_TLDS = {
    "co.uk", "org.uk", "me.uk", "ltd.uk", "plc.uk", "gov.uk", "ac.uk",
    "com.au", "net.au", "org.au", "co.nz", "com.br", "com.mx", "co.za",
    "co.jp", "co.in", "co.kr", "com.sg", "com.hk", "com.tr", "co.il",
    "com.ua", "com.pl", "com.es", "com.co", "com.ar", "com.tw",
}

# Hosts that are never single-niche Shopify stores; skip verifying them.
DEFAULT_HOST_BLOCKLIST = {
    "amazon.com", "amazon.co.uk", "amazon.ca", "ebay.com", "ebay.co.uk",
    "walmart.com", "target.com", "bestbuy.com", "homedepot.com", "lowes.com",
    "aliexpress.com", "alibaba.com", "etsy.com", "wish.com", "temu.com",
    "wayfair.com", "costco.com", "dickssportinggoods.com", "cabelas.com",
    "basspro.com", "academy.com", "rei.com", "newegg.com", "sears.com",
    "youtube.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "pinterest.com", "reddit.com", "tiktok.com", "linkedin.com", "quora.com",
    "wikipedia.org", "google.com", "bing.com", "duckduckgo.com", "yahoo.com",
    "yelp.com", "tripadvisor.com", "wordpress.com", "blogspot.com",
    "shopify.com", "myshopify.com", "apps.shopify.com", "help.shopify.com",
    "shopifycdn.com", "shopifysvc.com", "shopifycloud.com", "shopify.dev",
    "shopifystatus.com", "shopifyplus.com",
    "medium.com", "github.com", "apple.com", "microsoft.com", "gov",
    # Common affiliate/redirect/tracking hosts that leak in via listicles.
    "sjv.io", "pxf.io", "sovrn.com", "redirectingat.com", "viglink.com",
    "skimresources.com", "go.redirectingat.com", "anrdoezrs.net",
    "dpbolvw.net", "kqzyfj.com", "jdoqocy.com", "tkqlhce.com",
    "shareasale.com", "avantlink.com", "impactradius.com", "linksynergy.com",
    "bit.ly", "goo.gl", "t.co", "ow.ly", "tinyurl.com", "amzn.to",
    "doubleclick.net", "googlesyndication.com", "googletagmanager.com",
}


def build_opener(ca_bundle: str | None = None) -> urllib.request.OpenerDirector:
    """Build a urllib opener honoring environment proxies and an optional CA bundle.

    The CA bundle is auto-detected from SHOPIFY_FINDER_CA_BUNDLE, then from the
    known sandbox path, so the tool works unchanged behind a proxy or on a
    normal machine.
    """
    ca = ca_bundle or os.environ.get("SHOPIFY_FINDER_CA_BUNDLE")
    if not ca and os.path.exists("/root/.ccr/ca-bundle.crt"):
        ca = "/root/.ccr/ca-bundle.crt"

    if ca and os.path.exists(ca):
        ctx = ssl.create_default_context(cafile=ca)
    else:
        ctx = ssl.create_default_context()

    handlers = [
        urllib.request.ProxyHandler(urllib.request.getproxies()),
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPRedirectHandler(),
    ]
    return urllib.request.build_opener(*handlers)


class RateLimiter:
    """Simple global + per-host politeness limiter (thread-safe)."""

    def __init__(self, global_delay: float = 0.0, per_host_delay: float = 1.0):
        self.global_delay = global_delay
        self.per_host_delay = per_host_delay
        self._lock = threading.Lock()
        self._last_global = 0.0
        self._last_host: dict[str, float] = {}

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            waits = []
            if self.global_delay:
                waits.append(self._last_global + self.global_delay - now)
            if self.per_host_delay:
                waits.append(self._last_host.get(host, 0.0) + self.per_host_delay - now)
            delay = max([w for w in waits] + [0.0])
        if delay > 0:
            time.sleep(delay)
        with self._lock:
            now = time.monotonic()
            self._last_global = now
            self._last_host[host] = now


@dataclass
class HttpClient:
    """Thin HTTP client with retries, gzip, size caps, and rate limiting."""

    timeout: float = 20.0
    user_agent: str = DEFAULT_UA
    retries: int = 2
    rate: RateLimiter = field(default_factory=RateLimiter)
    _opener: urllib.request.OpenerDirector | None = None

    def __post_init__(self):
        self._opener = build_opener()

    def _host(self, url: str) -> str:
        return urllib.parse.urlsplit(url).hostname or ""

    def get(
        self,
        url: str,
        *,
        max_bytes: int = 300_000,
        headers: dict | None = None,
        polite: bool = True,
    ) -> tuple[int, dict, bytes]:
        """Return (status, headers_lower, body). Never raises on HTTP errors."""
        host = self._host(url)
        h = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip"}
        if headers:
            h.update(headers)
        last_exc = None
        for attempt in range(self.retries + 1):
            if polite:
                self.rate.wait(host)
            try:
                req = urllib.request.Request(url, headers=h)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read(max_bytes + 1)
                    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                        try:
                            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(max_bytes + 1)
                        except OSError:
                            pass
                    rh = {k.lower(): v for k, v in resp.headers.items()}
                    return resp.status, rh, raw[:max_bytes]
            except urllib.error.HTTPError as e:
                rh = {k.lower(): v for k, v in (e.headers or {}).items()}
                try:
                    body = e.read(max_bytes)
                except Exception:
                    body = b""
                return e.code, rh, body
            except Exception as e:  # noqa: BLE001 - network best-effort
                last_exc = e
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        LOG.debug("GET failed %s: %s", url, last_exc)
        return 0, {}, b""

    def get_json(self, url: str, *, max_bytes: int = 2_000_000, **kw):
        status, headers, body = self.get(url, max_bytes=max_bytes, **kw)
        ctype = headers.get("content-type", "").lower()
        if status != 200 or "json" not in ctype:
            return status, headers, None
        try:
            return status, headers, json.loads(body.decode("utf-8", "ignore"))
        except (ValueError, UnicodeDecodeError):
            return status, headers, None


# --------------------------------------------------------------------------- #
# URL / domain helpers
# --------------------------------------------------------------------------- #

def registrable_domain(host: str) -> str:
    """Reduce a hostname to its registrable domain (best-effort, stdlib only)."""
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or host.replace(".", "").isdigit():
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last2 = ".".join(parts[-2:])
    last3 = ".".join(parts[-3:])
    if last2 in _MULTI_TLDS:
        return last3
    return last2


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def normalize_domain(url_or_host: str) -> str | None:
    """Extract the registrable domain from a URL or bare host, or None."""
    s = (url_or_host or "").strip()
    if not s:
        return None
    if "://" not in s:
        s = "http://" + s
    host = host_of(s)
    if not host or "." not in host:
        return None
    return registrable_domain(host)


def is_blocked(domain: str, blocklist: set[str]) -> bool:
    if domain in blocklist:
        return True
    # Block obvious non-store TLD-only tokens.
    return any(domain == b or domain.endswith("." + b) for b in blocklist)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
