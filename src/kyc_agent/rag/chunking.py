from __future__ import annotations

from dataclasses import dataclass
import re
from .loaders import TextUnit


@dataclass
class TextChunk:
    text: str
    source: str
    unit_id: str
    chunk_index: int


def _split_boundaries(text: str) -> list[str]:
    # Preserve paragraph/sentence boundaries before falling back to hard character cuts.
    pieces = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    return [piece.strip() for piece in pieces if piece.strip()]


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    if chunk_size < 100:
        raise ValueError("chunk_size must be at least 100 characters")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sentences = _split_boundaries(text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # A single long sentence is split into overlapping windows.
        if len(sentence) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(sentence):
                end = min(start + chunk_size, len(sentence))
                chunks.append(sentence[start:end].strip())
                if end == len(sentence):
                    break
                start = end - overlap
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Carry a tail from the previous chunk to preserve context.
            tail = current[-overlap:] if overlap and current else ""
            current = f"{tail} {sentence}".strip() if tail else sentence
            if len(current) > chunk_size:
                current = current[-chunk_size:]
    if current:
        chunks.append(current)
    return chunks


def chunk_units(units: list[TextUnit], chunk_size: int = 1000, overlap: int = 150) -> list[TextChunk]:
    result = []
    for unit in units:
        for index, text in enumerate(chunk_text(unit.text, chunk_size, overlap)):
            result.append(TextChunk(text, unit.source, unit.unit_id, index))
    return result
