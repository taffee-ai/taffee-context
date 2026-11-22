#!/bin/bash
# Generates a self-signed TLS cert for the MCP server, once. Fine on a private network; on a real deployment terminate
# TLS at a load balancer with a managed certificate instead. Extra addresses the server is reached at go in
# MCP_CERT_IPS (comma separated), for example MCP_CERT_IPS=10.0.0.5.
set -eu
DIR=${1:-$HOME/.taffee-mcp}
mkdir -p "$DIR"
if [ -f "$DIR/mcp-cert.pem" ] && [ -f "$DIR/mcp-key.pem" ]; then
  echo "cert already present in $DIR (delete both files there to regenerate)"; exit 0
fi
SAN="DNS:localhost,IP:127.0.0.1"
for ip in $(echo "${MCP_CERT_IPS:-}" | tr ',' ' '); do SAN="$SAN,IP:$ip"; done
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -keyout "$DIR/mcp-key.pem" -out "$DIR/mcp-cert.pem" \
  -subj "/CN=code-graph-mcp" -addext "subjectAltName=$SAN"
chmod 600 "$DIR/mcp-key.pem"
echo "generated $DIR/mcp-cert.pem and mcp-key.pem"
