"""store_finder — discover Shopify and WooCommerce stores in a niche/category.

A dependency-free (standard-library only) toolkit that:
  1. Takes a category/niche you type in (or a curated niche file).
  2. Expands it into many search queries.
  3. Discovers candidate domains via pluggable search backends.
  4. Verifies which candidates run on Shopify or WooCommerce.
  5. Confirms each store actually sells in the target niche.
  6. Writes deduplicated, resumable results to CSV/JSONL.

See the package README for usage.
"""

__version__ = "0.2.0"
