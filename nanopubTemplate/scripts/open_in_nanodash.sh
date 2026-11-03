#!/usr/bin/env bash
# Open an already-signed nanopub .trig file in a local Nanodash instance's
# /view page. Nothing is published -- the signed TriG is base64url-encoded
# into the _nanopub_trig query param and rendered client-side.
#
# Usage: ./open_in_nanodash.sh <path-to-signed.trig> [port]
#   port defaults to 37373 (Nanodash's standard local default).
#
# Requires a locally running Nanodash instance on that port.

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <path-to-signed.trig> [port]" >&2
  exit 1
fi

TRIG_FILE="$1"
PORT="${2:-37373}"

if [ ! -f "$TRIG_FILE" ]; then
  echo "File not found: $TRIG_FILE" >&2
  exit 1
fi

NP_B64=$(base64 -i "$TRIG_FILE" | tr -d '\n' | tr '+/' '-_' | tr -d '=')
URL="http://localhost:${PORT}/view?_nanopub_trig=${NP_B64}"

echo "Opening: $URL"

if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"
else
  echo "Could not find 'open' or 'xdg-open'. Open this URL manually:"
  echo "$URL"
fi
