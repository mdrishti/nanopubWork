#!/usr/bin/env bash
# Sign an unpublished nanopub TriG file with the disposable preview key and
# open it in a local Nanodash instance for inspection. Nothing is published.
#
# Usage: ./preview-local.sh <path-to-template.trig> [port]
#   port defaults to 37373 (Nanodash's standard local default).

set -euo pipefail

SCRIPT_DIR="$(pwd)"
JAR="$SCRIPT_DIR/nanopub-1.95.1-jar-with-dependencies.jar"
KEY="$SCRIPT_DIR/preview-key/preview_id_rsa"
SIGNER="https://orcid.org/0000-0000-0000-0000"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <path-to-template.trig> [port]" >&2
  exit 1
fi

TRIG_FILE="$1"
PORT="${2:-37373}"

if [ ! -f "$TRIG_FILE" ]; then
  echo "File not found: $TRIG_FILE" >&2
  exit 1
fi
if [ ! -f "$JAR" ]; then
  echo "Nanopub CLI jar not found: $JAR" >&2
  exit 1
fi
if [ ! -f "$KEY" ]; then
  echo "Preview key not found: $KEY" >&2
  exit 1
fi

BASENAME="$(basename "$TRIG_FILE" .trig)"
SIGNED_FILE="$SCRIPT_DIR/${BASENAME}-preview-signed.trig"

echo "Signing $TRIG_FILE with the disposable preview key..."
java -jar "$JAR" sign -k "$KEY" -s "$SIGNER" -o "$SIGNED_FILE" "$TRIG_FILE"

NP_B64=$(base64 -i "$SIGNED_FILE" | tr -d '\n' | tr '+/' '-_' | tr -d '=')
URL="http://localhost:${PORT}/view?_nanopub_trig=${NP_B64}"

echo "$URL" > "$SCRIPT_DIR/preview-url-local.txt"
echo "Opening: $URL"

if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"
else
  echo "Could not find 'open' or 'xdg-open'. Open this URL manually:"
  echo "$URL"
fi
