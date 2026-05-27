#!/usr/bin/env bash
set -euo pipefail

export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export EMBEDDING_SERVER_URL="${EMBEDDING_SERVER_URL:-http://127.0.0.1:9000}"

uvicorn app.embedding_server:app \
  --host 127.0.0.1 \
  --port 9000 \
  --loop asyncio \
  --http h11 &

uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 7860 \
  --loop asyncio \
  --http h11
