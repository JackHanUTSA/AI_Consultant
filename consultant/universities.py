"""Local cache + index of the goal-kicker top-100 US universities knowledge base.

Source: https://github.com/JackHanUTSA/goal-kicker (knowledgebase/universities/*.json)

On first use, fetches each university JSON to `consultant/data/universities/<slug>.json`
and reads from disk thereafter. The cache directory is gitignored.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

RAW_BASE = (
    "https://raw.githubusercontent.com/JackHanUTSA/goal-kicker/main/"
    "knowledgebase/universities"
)

# Pinned slug list — matches the 100 *.json files in the repo as of 2026-05.
# If goal-kicker adds new schools, append the slug here.
SLUGS: tuple[str, ...] = (
    "american", "auburn", "baylor", "binghamton", "boston-college",
    "boston-university", "brandeis", "brown", "buffalo", "caltech",
    "carnegie-mellon", "case-western", "clemson", "colorado-school-of-mines",
    "columbia", "cornell", "dartmouth", "drexel", "duke", "emory",
    "florida-state", "fordham", "george-washington", "georgetown",
    "georgia-tech", "gonzaga", "harvard", "indiana-bloomington", "iowa-state",
    "johns-hopkins", "lehigh", "loyola-marymount", "marquette", "michigan",
    "michigan-state", "minnesota-twin-cities", "mit", "nc-state", "njit",
    "northeastern", "northwestern", "notre-dame", "nyu", "ohio-state",
    "oregon-state", "penn-state", "pepperdine", "pittsburgh", "princeton",
    "purdue", "rice", "rit", "rochester", "rutgers-new-brunswick",
    "santa-clara", "smu", "stanford", "stevens", "stony-brook", "syracuse",
    "tcu", "temple", "tennessee-knoxville", "texas-am", "tufts", "tulane",
    "uc-berkeley", "uc-davis", "uc-irvine", "uc-riverside", "uc-san-diego",
    "uc-santa-barbara", "uc-santa-cruz", "uchicago", "ucla", "uconn", "uf",
    "uiuc", "umass-amherst", "unc-chapel-hill", "university-of-delaware",
    "university-of-denver", "university-of-georgia", "university-of-miami",
    "university-of-san-diego", "university-of-washington", "upenn", "usc",
    "ut-austin", "uva", "vanderbilt", "villanova", "virginia-tech",
    "wake-forest", "washu", "william-and-mary", "wisconsin-madison", "wpi",
    "yale", "yeshiva",
)


class UniversityDB:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, dict] | None = None

    def _ensure_synced(self) -> None:
        missing = [s for s in SLUGS if not (self.cache_dir / f"{s}.json").exists()]
        if not missing:
            return
        print(f"Syncing {len(missing)} university records from goal-kicker...")
        for i, slug in enumerate(missing, 1):
            url = f"{RAW_BASE}/{slug}.json"
            with urllib.request.urlopen(url, timeout=30) as resp:
                (self.cache_dir / f"{slug}.json").write_bytes(resp.read())
            if i % 10 == 0 or i == len(missing):
                print(f"  {i}/{len(missing)}")

    def _load(self) -> dict[str, dict]:
        if self._records is None:
            self._ensure_synced()
            recs: dict[str, dict] = {}
            for slug in SLUGS:
                path = self.cache_dir / f"{slug}.json"
                if path.exists():
                    recs[slug] = json.loads(path.read_text("utf-8"))
            self._records = recs
        return self._records

    @staticmethod
    def _summary(rec: dict) -> dict:
        return {
            "slug": rec.get("slug"),
            "name": rec.get("name"),
            "short_name": rec.get("short_name"),
            "rank": rec.get("rank"),
            "majors_count": (rec.get("majors") or {}).get("count"),
        }

    @staticmethod
    def _trim(rec: dict) -> dict:
        """Drop the bulky school_people / evidence blocks before handing to the agent."""
        majors = rec.get("majors") or {}
        verification = rec.get("verification") or {}
        return {
            "slug": rec.get("slug"),
            "name": rec.get("name"),
            "short_name": rec.get("short_name"),
            "rank": rec.get("rank"),
            "official_domain": rec.get("official_domain"),
            "admissions_urls": (rec.get("source_urls") or {}).get("admissions", []),
            "majors": {
                "count": majors.get("count"),
                "titles": majors.get("titles", []),
            },
            "admissions": rec.get("admissions") or {},
            "competitive_signals": rec.get("competitive_signals") or {},
            "verification": {
                "last_verified_at": verification.get("last_verified_at"),
                "confidence": verification.get("confidence"),
                "unknown_fields": verification.get("unknown_fields", []),
            },
        }

    def list_all(self) -> list[dict]:
        return sorted(
            (self._summary(r) for r in self._load().values()),
            key=lambda r: r["rank"] if r["rank"] is not None else 999,
        )

    def get(self, slug: str) -> dict | None:
        rec = self._load().get(slug)
        return self._trim(rec) if rec else None

    def search(
        self,
        major: str | None = None,
        max_rank: int | None = None,
        name_contains: str | None = None,
    ) -> list[dict]:
        major_lc = major.lower() if major else None
        name_lc = name_contains.lower() if name_contains else None
        out: list[dict] = []
        for rec in self._load().values():
            if max_rank is not None and (rec.get("rank") or 999) > max_rank:
                continue
            if name_lc:
                hay = " ".join(
                    [rec.get("name") or "", rec.get("short_name") or ""]
                ).lower()
                if name_lc not in hay:
                    continue
            if major_lc:
                titles = (rec.get("majors") or {}).get("titles") or []
                if not any(major_lc in (t or "").lower() for t in titles):
                    continue
            out.append(self._summary(rec))
        out.sort(key=lambda r: r["rank"] if r["rank"] is not None else 999)
        return out
