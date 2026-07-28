"""shopify_finder — discover Shopify stores in a given niche/category.

A dependency-free (standard-library only) toolkit that:
  1. Expands a niche into many search queries.
  2. Discovers candidate domains via pluggable search backends.
  3. Verifies which candidates are real Shopify stores.
  4. Confirms each store actually sells in the target niche.
  5. Writes deduplicated, resumable results to CSV/JSONL.

See the project README for usage.
"""

__version__ = "0.1.0"
