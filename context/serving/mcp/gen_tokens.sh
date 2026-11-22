#!/bin/bash
# Generates one bearer token per named caller, once, clear text. Each caller is individually revocable: delete its line
# and restart the server. Never printed; read the file yourself when you need a value.
# Usage: gen_tokens.sh [tokens-file] [caller-name ...]   (default callers: agent-1 agent-2 test)
set -eu
FILE=${1:-$HOME/.taffee-mcp/tokens}
mkdir -p "$(dirname "$FILE")"
if [ -f "$FILE" ]; then echo "$FILE already exists (delete it to regenerate all tokens)"; exit 0; fi
umask 077
: > "$FILE"
shift || true
NAMES=("$@"); [ ${#NAMES[@]} -gt 0 ] || NAMES=(agent-1 agent-2 test)
for name in "${NAMES[@]}"; do
  echo "$name $(head -c 32 /dev/urandom | base64 | tr -d '=+/')" >> "$FILE"
done
echo "generated $FILE with tokens for: ${NAMES[*]}"
