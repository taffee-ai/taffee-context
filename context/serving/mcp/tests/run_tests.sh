#!/bin/bash
# Run on the test host. Builds the server image, starts a low-limit server over HTTPS (self-signed cert) and runs the
# rate-limit check against it. The container is capped (1 CPU / 1 GB with swap off).
#
# Needs: NEO4J_URI, NEO4J_PASSWORD (and NEO4J_USER, default neo4j) for a reachable Neo4j.
# Optional: TAFFEE_MCP_STATE (certs and tokens, default ~/.taffee-mcp), MCP_PORT (default 8775).
# The base image must exist first: docker build -f Dockerfile.base -t taffee-base:dev .   (repo root)
# Unit tests run separately: python -m pytest tests/   (in the taffee-mcp image)
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
STATE=${TAFFEE_MCP_STATE:-$HOME/.taffee-mcp}; RLPORT=$(( ${MCP_PORT:-8775} + 1 ))
: "${NEO4J_URI:?set NEO4J_URI}" "${NEO4J_PASSWORD:?set NEO4J_PASSWORD}"
export NEO4J_USER=${NEO4J_USER:-neo4j}
bash "$HERE/gen_cert.sh" "$STATE" && bash "$HERE/gen_tokens.sh" "$STATE/tokens" || exit 1
TOKEN=$(awk '$1=="test"{print $2}' "$STATE/tokens")
[ -n "$TOKEN" ] || { echo "no 'test' token in $STATE/tokens"; exit 1; }
docker build -q -t taffee-mcp:1 "$HERE" >/dev/null || exit 1
MOUNTS=(-v "$STATE/tokens:/run/tokens:ro" -v "$STATE/mcp-cert.pem:/run/cert.pem:ro" -v "$STATE/mcp-key.pem:/run/key.pem:ro")
COMMON=(-e NEO4J_URI -e NEO4J_USER -e NEO4J_PASSWORD -e TOKENS_FILE=/run/tokens -e SSL_CERTFILE=/run/cert.pem -e SSL_KEYFILE=/run/key.pem)
echo "--- rate limit (low-limit instance on port $RLPORT) ---"
docker rm -f taffee-mcp-rl >/dev/null 2>&1
docker run -d --name taffee-mcp-rl --network host --cpus 1 --memory 1g --memory-swap 1g "${COMMON[@]}" -e MCP_PORT="$RLPORT" \
  -e RATE_LIMIT_PER_MINUTE=3 "${MOUNTS[@]}" taffee-mcp:1 >/dev/null || exit 1
for i in $(seq 1 30); do curl -sk "https://127.0.0.1:$RLPORT/healthz" 2>/dev/null | grep -q ok && break; sleep 2; done
docker run --rm --network host --memory 300m --memory-swap 300m -e MCP_URL="https://127.0.0.1:$RLPORT/mcp" -e MCP_TOKEN="$TOKEN" \
  -v "$HERE/tests/test_rate_limit.py:/rl.py:ro" taffee-mcp:1 python /rl.py
RC=$?
docker rm -f taffee-mcp-rl >/dev/null 2>&1
exit $RC
