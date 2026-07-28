"""Niche configuration loading and search-query expansion.

A niche is defined by a small JSON file (see ``niches/``). From it we generate
a large, de-duplicated set of search queries designed to surface independent
stores selling in that niche.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

NICHES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "niches")


@dataclass
class Niche:
    name: str
    match_keywords: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    product_types: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)
    query_templates: list[str] = field(default_factory=list)
    seed_domains: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)

    @property
    def match_terms(self) -> list[str]:
        """All lowercase terms that indicate a product is in-niche."""
        terms = set()
        for group in (self.match_keywords, self.brands, self.product_types):
            for t in group:
                t = t.strip().lower()
                if t:
                    terms.add(t)
        return sorted(terms)


def load_niche(name_or_path: str) -> Niche:
    """Load a niche by name (looked up in niches/) or by explicit path."""
    path = name_or_path
    if not os.path.exists(path):
        cand = os.path.join(NICHES_DIR, name_or_path)
        for p in (cand, cand + ".json"):
            if os.path.exists(p):
                path = p
                break
        else:
            raise FileNotFoundError(
                f"Niche '{name_or_path}' not found. Provide a JSON path or a "
                f"file in {NICHES_DIR}."
            )
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    known = Niche.__dataclass_fields__.keys()
    return Niche(**{k: v for k, v in data.items() if k in known})


_DEFAULT_TEMPLATES = [
    "{term}",
    "{term} shop",
    "{term} store",
    "buy {term}",
    "{term} for sale",
    "{term} online store",
    "{term} online shop",
    "{term} dealer",
    "{term} specialist store",
    "shop {term}",
]


def expand_queries(niche: Niche, max_queries: int = 400) -> list[str]:
    """Produce an ordered, de-duplicated list of search queries for the niche.

    Ordering matters: the most specific, highest-signal queries come first so a
    small ``--max-queries`` budget still yields good candidates.
    """
    templates = niche.query_templates or _DEFAULT_TEMPLATES
    seen: set[str] = set()
    ordered: list[str] = []

    def add(q: str):
        q = " ".join(q.split()).strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            ordered.append(q)

    # 1) keyword x template — the core discovery grid.
    for kw in niche.match_keywords:
        for tpl in templates:
            add(tpl.format(term=kw, brand=""))

    # 2) brand-oriented queries (brand dealers/retailers are usually stores).
    for brand in niche.brands:
        add(f"{brand} {niche.name} dealer")
        add(f"{brand} {niche.name} store")
        add(f"buy {brand} {niche.name}")
        add(f"{brand} authorized dealer")

    # 3) product-type oriented queries.
    for pt in niche.product_types:
        add(f"{pt} store")
        add(f"buy {pt} online")

    # 4) directory / listicle discovery (harvested for outbound domains).
    add(f"best {niche.name} online stores")
    add(f"top {niche.name} retailers")
    add(f"{niche.name} shops list")
    add(f"where to buy {niche.name}")

    return ordered[:max_queries] if max_queries else ordered
