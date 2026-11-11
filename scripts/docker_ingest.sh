#!/bin/sh
set -eu

if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "OPENAI_API_KEY not set; skipping RAG ingestion."
    exit 0
fi

python scripts/build_vectorstore.py