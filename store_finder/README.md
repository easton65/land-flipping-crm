# store_finder

Type a **category/niche** and it builds a deduplicated list of **Shopify _and_
WooCommerce** stores that sell in it. It searches the web for candidate sites,
verifies each one's e-commerce platform, confirms the store actually sells in
your niche, and writes the results to CSV/JSONL.

Built with the Python **standard library only** — no `pip install` required.

---

## Quick start

```bash
# Interactive: it asks for the category, then searches Shopify + WooCommerce.
python -m store_finder

#   Enter a category / niche to search: metal detectors

# Or pass the niche directly:
python -m store_finder --niche "metal detectors" --target 3000

# Results:
#   results/<niche>.csv    (the list, with a `platform` column)
#   results/<niche>.db     (resumable state — rerun to continue)
```

Any phrase works as a niche — `"disc golf"`, `"cast iron cookware"`,
`"aquarium supplies"`. For a category you search often, save a curated niche
file (see below) for higher precision.

## How it works

```
niche (typed) ─▶ query expansion ─▶ discovery ─▶ platform verify ─▶ niche match ─▶ CSV/JSONL
                    (hundreds of      (search      Shopify:            products      (deduped,
                     queries)          backends)   /products.json      contain        resumable,
                                                   WooCommerce:        niche terms    platform
                                                   /wp-json/wc/store   (or homepage   tagged)
                                                   + HTML markers)     fallback)
```

1. **Query expansion** — your niche (keywords/brands/product types) is expanded
   into hundreds of targeted search queries.
2. **Discovery** — queries run through pluggable search backends to collect
   candidate domains; directory/"best-of" pages are harvested for the store
   links they contain (snowballing).
3. **Platform verification** — each candidate is checked for:
   - **Shopify** — `GET /products.json` returns genuine product JSON, Shopify
     response headers, or `cdn.shopify.com` / `myshopify.com` HTML markers.
   - **WooCommerce** — `GET /wp-json/wc/store/v1/products` returns a product
     array, or `woocommerce` / `/wp-content/plugins/woocommerce/` HTML markers.
   - Stores that only return a JS "lander" are rejected (the API response must
     parse as a real product collection).
4. **Niche match** — the store's product feed (titles / types / categories /
   tags) is scanned for your niche terms, with retry on rate-limiting and a
   homepage-text fallback when the product API is blocked.
5. **Output** — deduplicated CSV/JSONL, each row tagged with its `platform`,
   backed by resumable SQLite state.

## Output columns

| column | meaning |
|---|---|
| `domain` | registrable domain (dedup key) |
| `name` | store title from the homepage `<title>` |
| `homepage` | `https://<domain>` |
| `platform` | `shopify` or `woocommerce` |
| `evidence` | how the platform was detected |
| `matched_terms` | niche terms found in the store's products |
| `match_hits` | number of matching products (or homepage terms) |
| `products_sampled` | how many products were inspected |
| `source` | discovery backend that surfaced it |
| `query` | the search query that surfaced it |

## Discovery backends

Selected with `--sources a,b,c`. The default (`duckduckgo`) needs **no API key**.
The keyed backends dramatically increase volume and reliability.

| source | key(s) needed | notes |
|---|---|---|
| `duckduckgo` | none | default; polite + rate-limited HTML scraping |
| `serper` | `SERPER_API_KEY` | google.serper.dev — best price/volume for scale |
| `serpapi` | `SERPAPI_API_KEY` | serpapi.com |
| `bing` | `BING_API_KEY` | Bing Web Search API |
| `google_cse` | `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | Google Custom Search |

```bash
export SERPER_API_KEY=...
python -m store_finder --niche "metal detectors" \
    --sources duckduckgo,serper --target 3000 --max-queries 400
```

> **Reaching thousands.** The keyless DuckDuckGo backend is polite and
> rate-limited, so it typically surfaces on the order of a few hundred verified
> stores per niche before results plateau. To push toward 2–3k+, add a keyed
> backend (`serper` is cheapest for volume) and raise `--max-queries`. Results
> dedupe across backends and across runs, so you can layer several passes.

## Useful flags

```
--niche TEXT|NAME|PATH  category to search (free text), or a curated niche in
                        niches/ (name or JSON path). Prompts if omitted.
--platforms LIST        shopify,woocommerce (default both)
--keywords a,b,c        extra niche keywords (refines a typed/ad-hoc niche)
--brands a,b,c          brand names to boost discovery + matching
--target N              stop after N in-niche stores (default 3000)
--sources a,b           discovery backends (default duckduckgo)
--max-queries N         cap expanded queries (default 400)
--workers N             concurrent verification workers (default 12)
--search-delay S        seconds between search requests (default 2.0)
--per-host-delay S      seconds between requests to the same store host (1.0)
--no-listicles          disable harvesting outbound links from directory pages
--any-store             keep every store found, even without a niche match
--min-hits N            matching products required to count in-niche (default 1)
--seed-file PATH        verify an external list of candidate domains
--no-discovery          skip web search; only verify seeds/seed-file/pending
--out PATH              CSV output path
--state PATH            SQLite state path (for resume)
--jsonl                 also write a JSONL export
--export-only           skip crawling; just export from the existing state DB
-v                      verbose progress
```

## Curated niche files (higher precision)

A typed niche works anywhere, but a curated JSON file in `niches/` gives better
recall and precision because it lists brands, product types, and seed stores.
Minimal shape:

```json
{
  "name": "disc golf",
  "match_keywords": ["disc golf", "putter disc", "distance driver", "disc golf basket"],
  "brands": ["Innova", "Discraft", "Dynamic Discs", "MVP", "Discmania"],
  "product_types": ["disc golf disc", "disc golf bag", "disc golf basket"],
  "seed_domains": ["example-discgolf-store.com"]
}
```

Then: `python -m store_finder --niche disc_golf --target 2000`

See `niches/metal_detectors.json` for a complete example. `results/metal_detectors.csv`
is an included sample list (Shopify + WooCommerce).

## Environment notes

- Honors standard `HTTP_PROXY` / `HTTPS_PROXY` env vars automatically.
- Behind a proxy with a custom CA, set `STORE_FINDER_CA_BUNDLE=/path/to/ca.crt`
  (or the legacy `SHOPIFY_FINDER_CA_BUNDLE`).
- Be a good citizen: keep `--search-delay` reasonable and don't hammer stores.
  Discovery relies on third-party search engines whose terms you should respect;
  for heavy/production use, prefer the official search-API backends.
