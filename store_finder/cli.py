"""Command-line interface for store_finder.

Type a category/niche and it searches Shopify + WooCommerce stores selling it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from .core import setup_logging, DEFAULT_HOST_BLOCKLIST
from .niche import build_adhoc_niche, load_niche, niche_file_exists
from .pipeline import Pipeline, RunConfig
from .state import State

ALL_SOURCES = ["duckduckgo", "serper", "serpapi", "bing", "google_cse"]
ALL_PLATFORMS = ["shopify", "woocommerce"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m store_finder",
        description="Find Shopify & WooCommerce stores in a category/niche you type in.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--niche", default=None,
                   help="Category/niche to search (free text), OR a curated niche "
                        "name/JSON path in niches/. If omitted, you'll be prompted.")
    p.add_argument("--platforms", default="shopify,woocommerce",
                   help="Which platforms to include: " + ",".join(ALL_PLATFORMS))
    p.add_argument("--keywords", default=None,
                   help="Extra comma-separated niche keywords (refines an ad-hoc niche).")
    p.add_argument("--brands", default=None,
                   help="Comma-separated brand names to boost discovery/matching.")
    p.add_argument("--target", type=int, default=3000,
                   help="Stop once this many in-niche stores are found.")
    p.add_argument("--sources", default="duckduckgo",
                   help="Comma-separated discovery backends: " + ",".join(ALL_SOURCES))
    p.add_argument("--max-queries", type=int, default=400,
                   help="Cap on the number of expanded search queries.")
    p.add_argument("--workers", type=int, default=12,
                   help="Concurrent store-verification workers.")
    p.add_argument("--per-host-delay", type=float, default=1.0,
                   help="Politeness delay (s) between requests to the same host.")
    p.add_argument("--search-delay", type=float, default=2.0,
                   help="Delay (s) between search-backend requests.")
    p.add_argument("--no-listicles", action="store_true",
                   help="Disable harvesting outbound domains from directory pages.")
    p.add_argument("--any-store", action="store_true",
                   help="Keep any Shopify/WooCommerce store, even without a niche match.")
    p.add_argument("--seed-file", default=None,
                   help="Text/CSV file of extra candidate domains (one per line).")
    p.add_argument("--no-discovery", action="store_true",
                   help="Skip web search; only verify seeds/seed-file/pending domains.")
    p.add_argument("--min-hits", type=int, default=1,
                   help="Min matching products (or homepage terms) to count in-niche.")
    p.add_argument("--out", default=None,
                   help="Output CSV path (default: results/<niche>.csv).")
    p.add_argument("--state", default=None,
                   help="SQLite state path for resume (default: results/<niche>.db).")
    p.add_argument("--jsonl", action="store_true", help="Also write a JSONL export.")
    p.add_argument("--export-only", action="store_true",
                   help="Skip crawling; just export from the existing state DB.")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "niche"


def _split(csv_val: str | None) -> list[str]:
    return [x.strip() for x in (csv_val or "").split(",") if x.strip()]


def _resolve_niche(args):
    """Return (niche, slug). Prompts interactively if --niche is missing."""
    raw = args.niche
    if not raw:
        try:
            raw = input("Enter a category / niche to search: ").strip()
        except EOFError:
            raw = ""
        if not raw:
            print("No niche provided.", file=sys.stderr)
            sys.exit(2)

    if niche_file_exists(raw):
        niche = load_niche(raw)
        slug = _slugify(os.path.splitext(os.path.basename(raw))[0])
    else:
        niche = build_adhoc_niche(raw, _split(args.keywords), _split(args.brands))
        slug = _slugify(raw)
    return niche, slug


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    niche, slug = _resolve_niche(args)
    platforms = [p for p in _split(args.platforms) if p in ALL_PLATFORMS]
    if not platforms:
        print(f"No valid platforms in --platforms; choose from {ALL_PLATFORMS}",
              file=sys.stderr)
        return 2

    os.makedirs("results", exist_ok=True)
    out_csv = args.out or os.path.join("results", f"{slug}.csv")
    state_path = args.state or os.path.join("results", f"{slug}.db")
    state = State(state_path)

    if not args.export_only:
        cfg = RunConfig(
            niche=niche,
            sources=_split(args.sources),
            platforms=platforms,
            target=args.target,
            max_queries=args.max_queries,
            workers=args.workers,
            per_host_delay=args.per_host_delay,
            search_delay=args.search_delay,
            harvest_listicles=not args.no_listicles,
            require_niche=not args.any_store,
            min_hits=args.min_hits,
            discover_enabled=not args.no_discovery,
            seed_file=args.seed_file,
            blocklist=set(DEFAULT_HOST_BLOCKLIST),
        )
        print(f"Searching {', '.join(platforms)} stores for: '{niche.name}'",
              file=sys.stderr)
        summary = Pipeline(cfg, state).run()
        print(f"\nDone in {summary['elapsed_sec']}s — checked {summary['checked']} "
              f"domains, {summary['in_niche']} in-niche "
              f"(shopify={summary['shopify']}, woocommerce={summary['woocommerce']}).",
              file=sys.stderr)

    n = state.export_csv(out_csv)
    print(f"Wrote {n} in-niche stores -> {out_csv}", file=sys.stderr)
    if args.jsonl:
        jp = os.path.splitext(out_csv)[0] + ".jsonl"
        state.export_jsonl(jp)
        print(f"Wrote JSONL -> {jp}", file=sys.stderr)
    state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
