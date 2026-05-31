"""Offline sample source.

Loads the bundled dataset produced by `python -m scout gen-sample`, which
scrapes recently incorporated Delaware Division of Corporations records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..models import Company
from .base import Source

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_companies.json"


class SampleSource(Source):
    name = "sample"

    def __init__(self, data_file: str | Path | None = None, **_: object) -> None:
        self.data_file = Path(data_file) if data_file else DATA_FILE

    def fetch(self, limit: int = 1000) -> Iterator[Company]:
        if not self.data_file.exists():
            raise FileNotFoundError(
                f"Sample data not found at {self.data_file}. "
                "Run `python -m scout gen-sample` to scrape Delaware records."
            )
        records = json.loads(self.data_file.read_text())
        for rec in records[:limit]:
            yield Company(
                name=rec["name"],
                source=rec.get("source", self.name),
                source_id=rec.get("source_id", rec["name"]),
                jurisdiction=rec.get("jurisdiction", "Delaware, USA"),
                formation_date=rec.get("formation_date"),
                website=rec.get("website"),
                description=rec.get("description", ""),
                founders=rec.get("founders", []),  # real officers from Form D
                raw=rec.get("raw", rec),
            )
