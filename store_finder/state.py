"""Resumable state: track seen domains, verification status, and store hits.

Backed by SQLite so a run can be stopped and resumed without re-doing work,
and so multiple runs against the same niche accumulate results.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import threading
import time
from dataclasses import asdict

from .verify import StoreResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    domain      TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|checked
    source      TEXT,
    query       TEXT,
    first_url   TEXT,
    added_at    REAL
);
CREATE TABLE IF NOT EXISTS stores (
    domain        TEXT PRIMARY KEY,
    name          TEXT,
    homepage      TEXT,
    platform      TEXT,
    is_store      INTEGER,
    in_niche      INTEGER,
    evidence      TEXT,
    matched_terms TEXT,
    match_hits    INTEGER,
    products      INTEGER,
    source        TEXT,
    query         TEXT,
    found_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_cand_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_store_niche ON stores(in_niche);
"""


class State:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(_SCHEMA)
        self.db.commit()

    # -- candidates -------------------------------------------------------- #
    def add_candidates(self, cands) -> int:
        """Insert new candidate domains; return the count of newly added."""
        added = 0
        with self._lock:
            for c in cands:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO candidates(domain,status,source,query,"
                    "first_url,added_at) VALUES(?,?,?,?,?,?)",
                    (c.domain, "pending", c.source, c.query, c.url, time.time()),
                )
                added += cur.rowcount
            self.db.commit()
        return added

    def take_pending(self, limit: int) -> list[tuple[str, str, str]]:
        """Atomically claim up to `limit` pending domains (domain, source, query)."""
        with self._lock:
            rows = self.db.execute(
                "SELECT domain,source,query FROM candidates WHERE status='pending' "
                "LIMIT ?", (limit,),
            ).fetchall()
            if rows:
                self.db.executemany(
                    "UPDATE candidates SET status='checked' WHERE domain=?",
                    [(r[0],) for r in rows],
                )
                self.db.commit()
        return rows

    def counts(self) -> dict:
        with self._lock:
            pending = self.db.execute(
                "SELECT COUNT(*) FROM candidates WHERE status='pending'"
            ).fetchone()[0]
            checked = self.db.execute(
                "SELECT COUNT(*) FROM candidates WHERE status='checked'"
            ).fetchone()[0]
            hits = self.db.execute(
                "SELECT COUNT(*) FROM stores WHERE in_niche=1"
            ).fetchone()[0]
            stores = self.db.execute(
                "SELECT COUNT(*) FROM stores WHERE is_store=1"
            ).fetchone()[0]
            by_plat = dict(self.db.execute(
                "SELECT platform, COUNT(*) FROM stores WHERE in_niche=1 "
                "GROUP BY platform"
            ).fetchall())
        return {"pending": pending, "checked": checked,
                "stores": stores, "in_niche": hits,
                "shopify": by_plat.get("shopify", 0),
                "woocommerce": by_plat.get("woocommerce", 0)}

    def has_candidate(self, domain: str) -> bool:
        with self._lock:
            return self.db.execute(
                "SELECT 1 FROM candidates WHERE domain=?", (domain,)
            ).fetchone() is not None

    # -- stores ------------------------------------------------------------ #
    def record_store(self, r: StoreResult) -> None:
        if not r.is_store:
            return
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO stores(domain,name,homepage,platform,"
                "is_store,in_niche,evidence,matched_terms,match_hits,products,"
                "source,query,found_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.domain, r.name, r.homepage, r.platform, int(r.is_store),
                 int(r.in_niche), r.evidence, ",".join(r.matched_terms),
                 r.match_hits, r.products_sampled, r.source, r.query, time.time()),
            )
            self.db.commit()

    def in_niche_stores(self) -> list[dict]:
        with self._lock:
            cur = self.db.execute(
                "SELECT domain,name,homepage,platform,evidence,matched_terms,"
                "match_hits,products,source,query FROM stores WHERE in_niche=1 "
                "ORDER BY match_hits DESC, domain ASC"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    # -- export ------------------------------------------------------------ #
    def export_csv(self, path: str) -> int:
        rows = self.in_niche_stores()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["domain", "name", "homepage", "platform", "evidence",
                        "matched_terms", "match_hits", "products_sampled",
                        "source", "query"])
            for r in rows:
                w.writerow([r["domain"], r["name"], r["homepage"], r["platform"],
                            r["evidence"], r["matched_terms"], r["match_hits"],
                            r["products"], r["source"], r["query"]])
        return len(rows)

    def export_jsonl(self, path: str) -> int:
        rows = self.in_niche_stores()
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return len(rows)

    def close(self):
        self.db.close()
