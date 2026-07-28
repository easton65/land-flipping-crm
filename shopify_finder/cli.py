"""Command-line interface for shopify_finder."""

from __future__ import annotations

import argparse
import os
import sys

from .core import setup_logging, DEFAULT_HOST_BLOCKLIST
from .niche import load_niche
from .pipeline import Pipeline, RunConfig
from .state import State

ALL_SOURCES = ["duckduckgo", "serper", "serpapi", "bing", "google_cse"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m shopify_finder",
        description="Discover Shopify stores in a given niche/category.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--niche", required=True,
                   help="Niche name (a file in niches/) or a path to a niche JSON.")
    p.add_argument("--target", type=int, default=3000,
                   help="Stop once this many in-niche Shopify stores are found.")
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
    p.add_argument("--any-shopify", action="store_true",
                   help="Keep any Shopify store found, even without a niche match.")
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


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    niche = load_niche(args.niche)
    slug = os.path.splitext(os.path.basename(args.niche))[0]
    os.makedirs("results", exist_ok=True)
    out_csv = args.out or os.path.join("results", f"{slug}.csv")
    state_path = args.state or os.path.join("results", f"{slug}.db")

    state = State(state_path)

    if not args.export_only:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        cfg = RunConfig(
            niche=niche,
            sources=sources,
            target=args.target,
            max_queries=args.max_queries,
            workers=args.workers,
            per_host_delay=args.per_host_delay,
            search_delay=args.search_delay,
            harvest_listicles=not args.no_listicles,
            require_niche=not args.any_shopify,
            min_hits=args.min_hits,
            discover_enabled=not args.no_discovery,
            seed_file=args.seed_file,
            blocklist=set(DEFAULT_HOST_BLOCKLIST),
        )
        summary = Pipeline(cfg, state).run()
        print(f"\nDone in {summary['elapsed_sec']}s — "
              f"checked {summary['checked']} domains, "
              f"{summary['shopify']} Shopify, "
              f"{summary['in_niche']} in-niche.", file=sys.stderr)

    n = state.export_csv(out_csv)
    print(f"Wrote {n} in-niche Shopify stores -> {out_csv}", file=sys.stderr)
    if args.jsonl:
        jp = os.path.splitext(out_csv)[0] + ".jsonl"
        state.export_jsonl(jp)
        print(f"Wrote JSONL -> {jp}", file=sys.stderr)
    state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
