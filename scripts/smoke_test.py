#!/usr/bin/env python3
"""End-to-end sanity run on the committed sample.

Runs the full pipeline against ``data/samples/`` and prints what landed in the
graph. Requires: the AGE container up and Ollama running with a pulled model.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    from kg.config.loader import load_settings
    from kg.pipeline import run_pipeline
    from kg.store.age_store import AgeGraphStore

    settings = load_settings()
    sample = Path(__file__).resolve().parents[1] / "data" / "samples" / "example.txt"

    stats = run_pipeline(sample, settings=settings)
    print("ingest stats:", stats)

    store = AgeGraphStore.from_settings(settings)
    rows = store.query("MATCH (n) RETURN labels(n) AS lbl, n.name AS name LIMIT 20")
    print("sample nodes:", rows)


if __name__ == "__main__":
    main()
