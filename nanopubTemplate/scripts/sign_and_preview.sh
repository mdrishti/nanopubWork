#!/usr/bin/env bash
# Sign every .trig in a directory with the disposable preview key, in
# parallel (not serially -- each `sign` call does a slow network lookup to
# check whether the signer ORCID is already introduced), then write one
# Nanodash preview URL per file.
#
# Usage: ./sign_and_preview.sh <in_dir> <signed_out_dir> <preview-urls.txt> [port]
#
# Requires: the nanopub CLI jar and the preview key pair, both already
# present in ../nanopubstuff relative to this repo (see README.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STUFF_DIR="$(cd "$SCRIPT_DIR/../../../nanopubstuff" && pwd)"
JAR="$STUFF_DIR/nanopub-1.95.1-jar-with-dependencies.jar"
KEY="$SCRIPT_DIR/../preview-key/preview_id_rsa"
SIGNER="https://orcid.org/0000-0000-0000-0000"

if [ $# -lt 3 ]; then
  echo "Usage: $0 <in_dir> <signed_out_dir> <preview-urls.txt> [port]" >&2
  exit 1
fi

IN_DIR="$1"
OUT_DIR="$2"
URLS_FILE="$3"
PORT="${4:-37373}"

mkdir -p "$OUT_DIR"
: > "$URLS_FILE"

for f in "$IN_DIR"/*.trig; do
  base="$(basename "$f" .trig)"
  out="$OUT_DIR/${base}-signed.trig"
  if [ ! -f "$out" ]; then
    java -jar "$JAR" sign -k "$KEY" -s "$SIGNER" -o "$out" "$f" > /dev/null 2>&1 &
  fi
done
wait

for f in "$OUT_DIR"/*.trig; do
  b64=$(base64 -i "$f" | tr -d '\n' | tr '+/' '-_' | tr -d '=')
  echo "http://localhost:${PORT}/view?_nanopub_trig=${b64}" >> "$URLS_FILE"
done

echo "Signed $(ls "$OUT_DIR"/*.trig | wc -l | tr -d ' ') files; preview URLs written to $URLS_FILE"
