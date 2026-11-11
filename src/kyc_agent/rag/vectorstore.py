from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .chunking import chunk_units
from .loaders import load_document
from ..security.pii import redact_text

BASE_DIR = Path(__file__).resolve().parents[3]
DOCS_DIR = Path(os.getenv("RAG_DOCUMENTS_DIR", str(BASE_DIR / "documents")))
PERSIST_DIR = Path(os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_store")))
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "kyc_policy_knowledge")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def _embedding_function():
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to create/query the vector store.")
    import chromadb
    from chromadb.utils import embedding_functions
    return embedding_functions.OpenAIEmbeddingFunction(api_key=api_key, model_name=EMBEDDING_MODEL)


def build_vectorstore(documents_dir: str | Path = DOCS_DIR, persist_dir: str | Path = PERSIST_DIR,
                      chunk_size: int = 1000, overlap: int = 150) -> dict[str, Any]:
    documents_dir = Path(documents_dir)
    persist_dir = Path(persist_dir)
    if not documents_dir.exists():
        raise FileNotFoundError(f"Documents directory does not exist: {documents_dir}")
    allowed = {".pdf", ".docx", ".html", ".htm", ".csv", ".json", ".txt", ".md"}
    paths = sorted(p for p in documents_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed)
    if not paths:
        raise ValueError(f"No supported documents found in {documents_dir}")

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []
    total_redacted = 0
    per_file = []
    for path in paths:
        units = load_document(path)
        for unit in units:
            unit.text, counts = redact_text(unit.text)
            total_redacted += sum(counts.values())
        chunks = chunk_units(units, chunk_size=chunk_size, overlap=overlap)
        for chunk in chunks:
            ids.append(f"{chunk.source}::{chunk.unit_id}::{chunk.chunk_index}")
            texts.append(chunk.text)
            metadatas.append({"source": chunk.source, "unit_id": chunk.unit_id,
                              "chunk_index": chunk.chunk_index})
        per_file.append({"file": path.name, "units": len(units), "chunks": len(chunks)})

    persist_dir.mkdir(parents=True, exist_ok=True)
    import chromadb
    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=_embedding_function())
    # Chroma has practical request-size limits; add in batches.
    batch_size = 100
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.add(ids=ids[start:end], documents=texts[start:end], metadatas=metadatas[start:end])
    return {"files": len(paths), "chunks": len(texts), "redacted_items": total_redacted,
            "collection": COLLECTION_NAME, "persist_dir": str(persist_dir), "per_file": per_file}


def search_knowledge(query: str, n_results: int = 4, persist_dir: str | Path = PERSIST_DIR) -> list[dict]:
    if not os.getenv("OPENAI_API_KEY"):
        return []
    persist_dir = Path(persist_dir)
    if not persist_dir.exists():
        return []
    import chromadb
    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        collection = client.get_collection(name=COLLECTION_NAME, embedding_function=_embedding_function())
    except Exception:
        return []
    if collection.count() == 0:
        return []
    result = collection.query(query_texts=[query], n_results=min(max(n_results, 1), collection.count()), include=["documents", "metadatas", "distances"])
    output = []
    for idx, text in enumerate((result.get("documents") or [[]])[0]):
        metadata = (result.get("metadatas") or [[]])[0][idx] or {}
        distance = (result.get("distances") or [[]])[0][idx] if (result.get("distances") or [[]])[0] else None
        output.append({"text": text, "source": metadata.get("source", "unknown"),
                       "unit_id": metadata.get("unit_id", "unknown"),
                       "chunk_index": metadata.get("chunk_index", 0), "distance": distance})
    return output
