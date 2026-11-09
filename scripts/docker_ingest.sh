#!/bin/sh
set -eu
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is empty; skipping automatic ChromaDB ingestion."
  echo "Set OPENAI_API_KEY in .env and run: docker compose run --rm rag-ingest"
  exit 0
fi
python scripts/build_vectorstore.py
