"""Orchestration: expand queries -> discover -> verify -> record, resumably."""

from __future__ import annotations

import concurrent.futures as cf
import logging
import os
import time
from dataclasses import dataclass, field

from .core import HttpClient, RateLimiter, is_blocked, DEFAULT_HOST_BLOCKLIST
from .discovery import (BACKENDS, Candidate, harvest_outbound_domains,
                        looks_like_listicle)
from .niche import Niche, expand_queries
from .state import State
from .verify import verify_store

LOG = logging.getLogger("shopify_finder")


@dataclass
class RunConfig:
    niche: Niche
    sources: list[str] = field(default_factory=lambda: ["duckduckgo"])
    target: int = 3000
    max_queries: int = 400
    workers: int = 12
    per_host_delay: float = 1.0
    search_delay: float = 2.0
    harvest_listicles: bool = True
    require_niche: bool = True
    min_hits: int = 1
    discover_enabled: bool = True
    seed_file: str | None = None
    blocklist: set = field(default_factory=lambda: set(DEFAULT_HOST_BLOCKLIST))


class Pipeline:
    def __init__(self, cfg: RunConfig, state: State):
        self.cfg = cfg
        self.state = state
        # A gentle client for search endpoints, a faster one for store checks.
        self.search_client = HttpClient(
            rate=RateLimiter(global_delay=cfg.search_delay, per_host_delay=cfg.search_delay)
        )
        self.verify_client = HttpClient(
            timeout=15.0,
            rate=RateLimiter(global_delay=0.0, per_host_delay=cfg.per_host_delay),
        )

    # -- discovery --------------------------------------------------------- #
    def _queue(self, cands: list[Candidate]) -> int:
        keep = [c for c in cands if not is_blocked(c.domain, self.cfg.blocklist)]
        return self.state.add_candidates(keep)

    def _load_seed_file(self) -> int:
        """Load extra candidate domains from a text file (one per line / CSV col 1)."""
        from .core import normalize_domain
        path = self.cfg.seed_file
        if not path or not os.path.exists(path):
            return 0
        cands = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                token = line.split(",")[0].strip()  # tolerate CSV
                dom = normalize_domain(token)
                if dom:
                    cands.append(Candidate(dom, f"https://{dom}", "seed-file", "seedfile"))
        return self._queue(cands)

    def discover(self) -> None:
        # Seed domains (from niche file + optional --seed-file) go into the queue.
        seeds = [Candidate(d, f"https://{d}", "seed", "seed")
                 for d in self.cfg.niche.seed_domains]
        self._queue(seeds)
        n_file = self._load_seed_file()
        if n_file:
            LOG.info("Loaded %d candidate domains from seed file.", n_file)

        if not self.cfg.discover_enabled:
            LOG.info("Discovery disabled; verifying seeds/pending only.")
            return

        queries = expand_queries(self.cfg.niche, self.cfg.max_queries)

        LOG.info("Discovery: %d queries across sources %s",
                 len(queries), self.cfg.sources)
        for i, q in enumerate(queries, 1):
            found: list[Candidate] = []
            for src in self.cfg.sources:
                backend = BACKENDS.get(src)
                if not backend:
                    LOG.warning("Unknown source '%s' (skipping)", src)
                    continue
                try:
                    found.extend(backend(q, self.search_client))
                except Exception as e:  # noqa: BLE001
                    LOG.debug("backend %s failed on %r: %s", src, q, e)

            added = self._queue(found)

            # Snowball: harvest outbound domains from listicle/directory results.
            if self.cfg.harvest_listicles:
                for c in found:
                    if looks_like_listicle(c) and not is_blocked(c.domain, self.cfg.blocklist):
                        for dom in harvest_outbound_domains(c.url, self.search_client):
                            if not is_blocked(dom, self.cfg.blocklist):
                                added += self.state.add_candidates(
                                    [Candidate(dom, f"https://{dom}", q, "listicle")]
                                )

            if i % 10 == 0 or added:
                c = self.state.counts()
                LOG.info("[q %d/%d] +%d new  | pending=%d checked=%d shopify=%d in_niche=%d",
                         i, len(queries), added, c["pending"], c["checked"],
                         c["shopify"], c["in_niche"])
            if self.state.counts()["in_niche"] >= self.cfg.target:
                LOG.info("Target reached during discovery; stopping query expansion.")
                break

    # -- verification ------------------------------------------------------ #
    def _verify_one(self, domain: str, source: str, query: str):
        try:
            return verify_store(
                domain, self.cfg.niche, self.verify_client,
                source=source, query=query,
                require_niche=self.cfg.require_niche, min_hits=self.cfg.min_hits,
            )
        except Exception as e:  # noqa: BLE001
            LOG.debug("verify failed %s: %s", domain, e)
            return None

    def verify_all(self) -> None:
        pool = cf.ThreadPoolExecutor(max_workers=self.cfg.workers)
        while True:
            if self.state.counts()["in_niche"] >= self.cfg.target:
                LOG.info("Target of %d in-niche stores reached.", self.cfg.target)
                break
            batch = self.state.take_pending(self.cfg.workers * 4)
            if not batch:
                break
            futures = [pool.submit(self._verify_one, d, s, q) for d, s, q in batch]
            for fut in cf.as_completed(futures):
                r = fut.result()
                if r and r.is_shopify:
                    self.state.record_store(r)
                    if r.in_niche:
                        LOG.info("  ✓ %-35s %s", r.domain,
                                 ",".join(r.matched_terms[:4]))
            c = self.state.counts()
            LOG.info("Verify progress | pending=%d checked=%d shopify=%d in_niche=%d",
                     c["pending"], c["checked"], c["shopify"], c["in_niche"])
        pool.shutdown(wait=True)

    def run(self) -> dict:
        t0 = time.time()
        self.discover()
        self.verify_all()
        c = self.state.counts()
        c["elapsed_sec"] = round(time.time() - t0, 1)
        return c
