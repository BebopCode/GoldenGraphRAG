"""Loaders: read raw files into normalized :class:`Document` objects.

Supports .txt, .md, .json, .csv and dispatches by extension. Adding a format
is a new function + a line in ``_LOADERS``.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Document(BaseModel):
    """A normalized input document: id + text + provenance metadata."""

    id: str
    text: str
    source: str
    metadata: dict[str, str] = Field(default_factory=dict)


def _load_text(path: Path) -> str:
    """Read a file as UTF-8 text (the common case all loaders share)."""
    return path.read_text(encoding="utf-8")


def load_txt(path: Path) -> list[Document]:
    """Whole file as one document, id = filename stem."""
    return [Document(id=path.stem, text=_load_text(path), source=str(path))]


def load_md(path: Path) -> list[Document]:
    """Whole file as one document. Markdown is text; structure is recovered
    downstream by the structural chunker."""
    return [Document(id=path.stem, text=_load_text(path), source=str(path))]


def load_json(path: Path) -> list[Document]:
    """Each top-level item (or the whole object) becomes a document.

    Accepted shapes:
      * ``[{"id":..., "text":...}, ...]``
      * ``{"id":..., "text":...}``
      * ``{"key": "text", ...}``  -> one document per value
    """
    data = json.loads(_load_text(path))
    docs: list[Document] = []

    def make(doc_id: str, text: str, **extra: str) -> None:
        if text and text.strip():
            docs.append(Document(id=doc_id, text=text, source=str(path), metadata=extra))

    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                make(str(item.get("id", i)), str(item.get("text", "")), **_str_meta(item))
            elif isinstance(item, str):
                make(str(i), item)
    elif isinstance(data, dict):
        if "text" in data:
            make(str(data.get("id", path.stem)), str(data["text"]), **_str_meta(data))
        else:
            for k, v in data.items():
                if isinstance(v, str):
                    make(str(k), v)
    return docs


def load_csv(path: Path) -> list[Document]:
    """One document per row, joined columns or a ``text`` column if present."""
    docs: list[Document] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if "text" in row and row["text"]:
                text = row["text"]
            else:
                text = " ".join(f"{k}: {v}" for k, v in row.items() if v)
            meta = {k: v for k, v in row.items() if k != "text" and v}
            doc_id = str(row.get("id", i))
            if text.strip():
                docs.append(Document(id=doc_id, text=text, source=str(path), metadata=meta))
    return docs


def _str_meta(d: dict) -> dict[str, str]:
    """Non-id/text fields of a JSON item, stringified, as document metadata."""
    return {k: str(v) for k, v in d.items() if k not in ("id", "text")}


# Extension -> loader registry. Adding a format = adding a line here.
_LOADERS: dict[str, Callable[[Path], list[Document]]] = {
    ".txt": load_txt,
    ".md": load_md,
    ".json": load_json,
    ".csv": load_csv,
}


def load_document(path: str | Path) -> list[Document]:
    """Load a single file into one or more :class:`Document` objects."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {p}")
    loader = _LOADERS.get(p.suffix.lower())
    if loader is None:
        raise ValueError(f"Unsupported file type '{p.suffix}'. Supported: {sorted(_LOADERS)}")
    docs = loader(p)
    logger.info("Loaded %d document(s) from %s", len(docs), p)
    return docs


def load_dataset(path: str | Path) -> list[Document]:
    """Load a file or every supported file in a directory (recursively)."""
    p = Path(path)
    if p.is_dir():
        files = sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in _LOADERS)
        docs: list[Document] = []
        for f in files:
            docs.extend(load_document(f))
        return docs
    return load_document(p)
