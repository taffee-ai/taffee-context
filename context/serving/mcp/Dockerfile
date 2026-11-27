# mcp-service: read-only server over the graph and chunks. Built on taffee-base.
# Build context is the taffee-context repository root (it needs python/taffee_context for the storage layer):
#   docker build -f context/serving/mcp/Dockerfile .
FROM taffee-base:dev
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "mcp==1.30.0" "pydantic==2.13.5" "graphifyy==0.9.51" "neo4j>=5.28,<6"
WORKDIR /app
COPY context/serving/mcp/server.py context/serving/mcp/client.py context/serving/mcp/turbo_builder.py context/serving/mcp/turbo_data.py context/serving/mcp/turbo_git.py context/serving/mcp/turbo_knapsack.py context/serving/mcp/turbo_scorer.py context/serving/mcp/turbo_distiller.py /app/
COPY python/taffee_context /app/taffee_context
RUN cp /app/server.py /server.py && \
    NEO4J_URI=bolt://dummy:7687 NEO4J_USER=dummy NEO4J_PASSWORD=dummy \
    python -c "import server, client, turbo_builder, turbo_data, turbo_git, turbo_knapsack, turbo_scorer, turbo_distiller; print('BUILD OK: MCP server and turbo modules imported successfully')"
ENV PYTHONPATH=/app:/
EXPOSE 8765
CMD ["python", "/server.py"]
