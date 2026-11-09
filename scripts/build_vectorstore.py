"""Build/rebuild the persistent ChromaDB index from ./documents."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyc_agent.rag.vectorstore import build_vectorstore


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest, redact, chunk and embed KYC policy documents")
    parser.add_argument("--documents", default=None, help="Documents directory (default: ./documents)")
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("RAG_CHUNK_SIZE", "1000")))
    parser.add_argument("--overlap", type=int, default=int(os.getenv("RAG_CHUNK_OVERLAP", "150")))
    args = parser.parse_args()
    kwargs = {"chunk_size": args.chunk_size, "overlap": args.overlap}
    if args.documents:
        kwargs["documents_dir"] = args.documents
    print(json.dumps(build_vectorstore(**kwargs), indent=2))


if __name__ == "__main__":
    main()
