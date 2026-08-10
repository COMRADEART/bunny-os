#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Prepare the Linux reference target for the agent-provider gates.
#
# Run as `bunny`, from ext4, never from /mnt/c: a Linux git over 9p reports
# hundreds of spurious modifications and runs an order of magnitude slower.
# Invoked as a *file* rather than through `wsl -- bash -lc '...'`, because the
# agent harness mangles $VAR and $(...) before they reach the shell.
set -euo pipefail

WORKTREE="${WORKTREE:-/home/bunny/agents-work}"
MODEL_DIR="${MODEL_DIR:-$HOME/.local/share/bunny-os/agent-models}"
MODEL_FILE="${MODEL_FILE:-qwen2.5-0.5b-instruct-q4_k_m.gguf}"
PORT="${PORT:-8080}"
LOG_DIR="${LOG_DIR:-/home/bunny/agents-ops}"

mkdir -p "$LOG_DIR"

case "${1:-}" in
  sync)
    # A fresh ext4 copy of the working tree at the commit under test. rsync
    # rather than git clone: the tree may hold uncommitted work in progress
    # and the gates must run what is actually there.
    mkdir -p "$WORKTREE"
    rsync -a --delete \
      --exclude '.git/' --exclude '__pycache__/' --exclude 'node_modules/' \
      --exclude 'build/out/' \
      /mnt/c/Users/allam/Documents/new/bunny-os/ "$WORKTREE/"
    echo "synced to $WORKTREE"
    ;;

  serve)
    # llama-server on loopback, with the model the slice will discover.
    # --host 127.0.0.1 explicitly: the adapter refuses a non-loopback http
    # target, and a server listening on 0.0.0.0 would be a wider surface than
    # the configuration claims.
    if [ ! -f "$MODEL_DIR/$MODEL_FILE" ]; then
      echo "model $MODEL_DIR/$MODEL_FILE is absent" >&2
      exit 2
    fi
    exec /usr/bin/llama-server \
      --model "$MODEL_DIR/$MODEL_FILE" \
      --host 127.0.0.1 --port "$PORT" \
      --ctx-size 4096 --n-predict 512 \
      --threads 4 --no-warmup \
      --log-file "$LOG_DIR/llama-server.log"
    ;;

  wait)
    # Block until the server answers /health, or give up with a status.
    for _ in $(seq 1 120); do
      if curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        echo "llama-server is answering on 127.0.0.1:$PORT"
        exit 0
      fi
      sleep 1
    done
    echo "llama-server did not answer within 120s" >&2
    exit 1
    ;;

  models)
    curl -sf -m 5 "http://127.0.0.1:$PORT/v1/models" || exit 1
    echo
    ;;

  stop)
    pkill -f 'llama-server --model' || true
    echo "stopped"
    ;;

  *)
    echo "usage: agents-env.sh {sync|serve|wait|models|stop}" >&2
    exit 64
    ;;
esac
