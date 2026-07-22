"""Structure-aware chunker.

Splits along the document's natural structure — markdown headers first, and a
heuristic section detector (ALL-CAPS titles, ``Article N`` / ``Part N`` /
numbered headings) as a fallback. The active heading *path* is carried into each
chunk's metadata so the extractor still knows where a chunk came from.

Structure-aware chunking measurably beats fixed-size splitting because it keeps
entities and their surrounding context on the same side of a chunk boundary.
"""

from __future__ import annotations

import re

from kg.ingest.chunkers.base import Chunk, Chunker
from kg.ingest.loaders import Document

_MD_HEADER = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# Heuristic section titles for plain text: "Article 21", "Section 4.", "1. Title".
# (ALL-CAPS titles like "PREAMBLE" / "Part III" are detected in code — see below —
# because a regex [A-Z]+ under IGNORECASE would greedily match ordinary sentences.)
_SECTION_HEADER = re.compile(
    r"""^(
        (?:article|art|part|chapter|section|sec)\.?\s*\d+[a-zA-Z.]*(?:[:\-\s].*)?  # Article N
        | \d+[.)]\s+\S.*                                                           # 1. Title
    )$""",
    re.VERBOSE | re.IGNORECASE,
)


def _looks_like_caps_title(line: str) -> bool:
    """True for ALL-CAPS title lines: ``PREAMBLE``, ``Part III``, ``FUNDAMENTAL RIGHTS``.

    Requires *every* alphabetic character to be uppercase, so normal sentences
    (which contain lowercase letters) never qualify.
    """
    s = line.strip()
    if not (3 <= len(s) <= 120):
        return False
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _is_blank(line: str) -> bool:
    return not line.strip()


class StructuralChunker(Chunker):
    def __init__(self, max_chars: int | None = None) -> None:
        # Optional cap: if a single section is huge, the extractor prompt can blow up.
        self.max_chars = max_chars

    def chunk(self, document: Document) -> list[Chunk]:
        lines = document.text.splitlines()
        if not any(line.strip() for line in lines):
            return []

        use_markdown = any(_MD_HEADER.match(line) for line in lines)
        sections = self._split_markdown(lines) if use_markdown else self._split_heuristic(lines)

        # Keep only sections with non-empty bodies.
        sections = [(h, b.strip()) for h, b in sections if b and b.strip()]
        if not sections:
            # Only headers / whitespace: treat the whole document as one chunk.
            if document.text.strip():
                return [
                    self._mk(
                        document,
                        0,
                        document.text.strip(),
                        "",
                        "",
                        note="no structure detected; whole document",
                    )
                ]
            return []

        # Did we find *any* heading? If not, this is an unstructured blob.
        has_structure = any(heading for heading, _ in sections)

        chunks: list[Chunk] = []
        idx = 0
        for path, body in sections:
            heading = path.split(" > ")[-1] if path else ""
            if self.max_chars and len(body) > self.max_chars:
                # Section too big: slide a window over it, keeping the heading as context.
                for i in range(0, len(body), self.max_chars):
                    piece = body[i : i + self.max_chars].strip()
                    if piece:
                        chunks.append(self._mk(document, idx, piece, heading, path))
                        idx += 1
            else:
                chunks.append(self._mk(document, idx, body, heading, path))
                idx += 1

        if not has_structure:
            for c in chunks:
                c.metadata["note"] = "no structure detected; whole document"
        return chunks

    def _mk(
        self,
        document: Document,
        idx: int,
        text: str,
        heading: str,
        path: str,
        note: str | None = None,
    ) -> Chunk:
        meta = {"strategy": "structural", "index": idx, **document.metadata}
        if heading:
            meta["heading"] = heading
        if path:
            meta["path"] = path
        if note:
            meta["note"] = note
        return Chunk(
            id=f"{document.id}#{idx}",
            text=text,
            document_id=document.id,
            source=document.source,
            metadata=meta,
        )

    def _split_markdown(self, lines: list[str]) -> list[tuple[str, str]]:
        """Return [(heading_path, body), ...] from markdown headers."""
        sections: list[tuple[str, str]] = []
        stack: list[tuple[int, str]] = []  # (level, title)
        current_path = ""
        current_body: list[str] = []

        def flush() -> None:
            if current_body and (current_path or any(line.strip() for line in current_body)):
                sections.append((current_path, "\n".join(current_body)))

        for line in lines:
            m = _MD_HEADER.match(line)
            if m:
                flush()
                level = len(m.group(1))
                title = m.group(2).strip()
                # pop stack to the right depth
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                current_path = " > ".join(t for _, t in stack)
                current_body = []
            else:
                current_body.append(line)
        flush()
        return sections

    def _split_heuristic(self, lines: list[str]) -> list[tuple[str, str]]:
        """Return [(heading, body), ...] using section-header heuristics."""
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_body: list[str] = []

        def flush() -> None:
            if current_body and any(line.strip() for line in current_body):
                sections.append((current_heading, "\n".join(current_body)))

        for line in lines:
            stripped = line.strip()
            if stripped and (_SECTION_HEADER.match(stripped) or _looks_like_caps_title(stripped)):
                flush()
                current_heading = stripped
                current_body = []
            else:
                current_body.append(line)
        flush()
        return sections
