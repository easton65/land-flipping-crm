# shopify_finder

A reusable, dependency-free tool for building **large lists of Shopify stores in
a given niche/category** (e.g. metal detectors). It searches the web for
candidate sites, verifies which ones actually run on Shopify, confirms each
store really sells in your niche, and writes a deduplicated, resumable list to
CSV/JSONL.

Built with the Python **standard library only** — no `pip install` required.

---

## How it works

```
niche.json ──▶ query expansion ──▶ discovery ──▶ Shopify verify ──▶ niche match ──▶ CSV/JSONL
 (keywords,       (hundreds of        (search       (products.json    (products/tags     (deduped,
  brands,          targeted            backends)     + headers +        contain niche      resumable)
  seeds)           queries)                          HTML markers)      terms)
```

1. **Query expansion** — a niche file (keywords, brands, product types, seed
   domains) is expanded into hundreds of targeted search queries.
2. **Discovery** — queries run through pluggable search backends to collect
   candidate domains. Directory/"best-of" pages are also harvested for the
   outbound store links they contain (snowballing).
3. **Shopify verification** — each candidate is checked three ways:
   - `GET /products.json` returns genuine JSON with a `products` array,
   - response headers include Shopify markers (`x-shopify-stage`, `x-shopid`, …),
   - homepage HTML references `cdn.shopify.com` / `Shopify.shop` / `myshopify.com`.
4. **Niche match** — the store's `products.json` (title / product_type / tags /
   vendor) is scanned for your niche's terms so unrelated Shopify stores are
   dropped. Falls back to homepage text if `products.json` is unavailable.
5. **Output** — in-niche stores are written to CSV (and optionally JSONL),
   deduplicated by registrable domain. State lives in SQLite so runs are
   **resumable** and repeat runs accumulate results.

## Quick start

```bash
# From the repo root. Finds metal-detector Shopify stores (keyless default).
python -m shopify_finder --niche metal_detectors --target 3000

# Results:
#   results/metal_detectors.csv    (the list)
#   results/metal_detectors.db     (resumable state — rerun to continue)
```

Re-running the same command **resumes** and adds more; delete the `.db` to start
fresh. Export the current DB without crawling:

```bash
python -m shopify_finder --niche metal_detectors --export-only
```

## Output columns

| column | meaning |
|---|---|
| `domain` | registrable domain (dedup key) |
| `name` | store title from the homepage `<title>` |
| `homepage` | `https://<domain>` |
| `shopify_evidence` | how Shopify was detected (`products.json` / `header` / `html-marker`) |
| `matched_terms` | niche terms found in the store's products |
| `match_hits` | number of matching products (or homepage terms) |
| `products_sampled` | how many products were inspected |
| `source` | discovery backend that surfaced it |
| `query` | the search query that surfaced it |

## Discovery backends

Selected with `--sources a,b,c`. The default (`duckduckgo`) needs **no API key**.
The keyed backends dramatically increase volume and reliability — set the
relevant environment variable and add the source.

| source | key(s) needed | notes |
|---|---|---|
| `duckduckgo` | none | default; polite + rate-limited HTML scraping |
| `serper` | `SERPER_API_KEY` | google.serper.dev — best price/volume for scale |
| `serpapi` | `SERPAPI_API_KEY` | serpapi.com |
| `bing` | `BING_API_KEY` | Bing Web Search API |
| `google_cse` | `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | Google Custom Search |

```bash
export SERPER_API_KEY=...   # or SERPAPI_API_KEY / BING_API_KEY
python -m shopify_finder --niche metal_detectors \
    --sources duckduckgo,serper --target 3000 --max-queries 400
```

> **Reaching thousands.** The keyless DuckDuckGo backend is polite and
> rate-limited, so it typically surfaces on the order of a few hundred verified
> stores per niche before results plateau. To push toward 2–3k+, add a keyed
> backend (`serper` is the cheapest for volume) and raise `--max-queries`. The
> tool dedupes across backends and runs, so you can layer several passes.

## Useful flags

```
--niche NAME|PATH     niche file in niches/ (e.g. metal_detectors) or a JSON path
--target N            stop after N in-niche stores (default 3000)
--sources a,b         discovery backends (default duckduckgo)
--max-queries N       cap expanded queries (default 400)
--workers N           concurrent verification workers (default 12)
--search-delay S      seconds between search requests (default 2.0; be polite)
--per-host-delay S    seconds between requests to the same store host (default 1.0)
--no-listicles        disable harvesting outbound links from directory pages
--any-shopify         keep every Shopify store found, even without a niche match
--min-hits N          matching products required to count as in-niche (default 1)
--out PATH            CSV output path
--state PATH          SQLite state path (for resume)
--jsonl               also write a JSONL export
--export-only         skip crawling; just export from the existing state DB
-v                    verbose progress
```

## Adding a new niche

Drop a JSON file in `niches/`. Minimal shape:

```json
{
  "name": "disc golf",
  "match_keywords": ["disc golf", "putter disc", "distance driver", "disc golf basket"],
  "brands": ["Innova", "Discraft", "Dynamic Discs", "MVP", "Discmania"],
  "product_types": ["disc golf disc", "disc golf bag", "disc golf basket"],
  "seed_domains": ["example-discgolf-store.com"]
}
```

Then: `python -m shopify_finder --niche disc_golf --target 2000`

See `niches/metal_detectors.json` for a complete example (it also supports
`query_templates` and `negative_keywords`).

## Environment notes

- Honors standard `HTTP_PROXY` / `HTTPS_PROXY` env vars automatically.
- Behind a proxy with a custom CA, set `SHOPIFY_FINDER_CA_BUNDLE=/path/to/ca.crt`.
- Be a good citizen: keep `--search-delay` reasonable and don't hammer stores.
  Discovery relies on third-party search engines whose terms you should respect;
  for heavy/production use, prefer the official search-API backends.
```
