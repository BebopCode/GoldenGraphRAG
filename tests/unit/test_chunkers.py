"""Chunker tests: structural context preserved, fixed windows overlap."""

from __future__ import annotations

import pytest

from kg.ingest.chunkers.fixed import FixedChunker
from kg.ingest.chunkers.structural import StructuralChunker
from kg.ingest.loaders import Document


def _doc(text: str, doc_id: str = "d") -> Document:
    return Document(id=doc_id, text=text, source=f"{doc_id}.md")


MD = """# Part III

## Article 21

No person shall be deprived of life or liberty.

## Article 14

The State shall not deny equality before the law.
"""


def test_structural_markdown_preserves_headings() -> None:
    chunks = StructuralChunker().chunk(_doc(MD))
    texts = " ||| ".join(c.text for c in chunks)
    assert any("Article 21" in c.metadata.get("heading", "") for c in chunks)
    assert any("Article 14" in c.metadata.get("heading", "") for c in chunks)
    assert "life or liberty" in texts
    assert "equality before the law" in texts
    # paths nest: "Part III > Article 21"
    paths = [c.metadata.get("path", "") for c in chunks]
    assert any("Part III > Article 21" in p for p in paths)


def test_structural_plain_text_detects_sections() -> None:
    text = (
        "Article 21\nNo person shall be deprived of life.\n\nArticle 14\nEquality before the law.\n"
    )
    chunks = StructuralChunker().chunk(_doc(text, "plain"))
    headings = [c.metadata.get("heading", "") for c in chunks]
    assert "Article 21" in headings
    assert "Article 14" in headings


def test_structural_no_structure_falls_back_to_whole() -> None:
    chunks = StructuralChunker().chunk(_doc("just one plain paragraph with no headings", "x"))
    assert len(chunks) == 1
    assert chunks[0].metadata.get("note", "").startswith("no structure")


def test_fixed_overlap_windows() -> None:
    text = " ".join(f"word{i}" for i in range(200))
    chunks = FixedChunker(chunk_size=50, overlap=20).chunk(_doc(text, "f"))
    assert len(chunks) >= 2
    # overlap guarantees the tail of chunk i appears near the head of chunk i+1
    assert chunks[0].text.split()[-1] in chunks[1].text


def test_fixed_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError):
        FixedChunker(chunk_size=10, overlap=10)
