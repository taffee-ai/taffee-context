# Evaluation runner: drives the agent, implements the tools, records each run.
# Build from the repository root: docker build -f eval/Dockerfile -t taffee-eval:dev .
FROM taffee-base:dev
# Same mcp/pydantic pins as the MCP server image (context/serving/mcp/Dockerfile).
RUN pip install --no-cache-dir "mcp==1.16.0" "pydantic==2.13.5" "httpx>=0.27" "tiktoken==0.9.0" \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"
COPY eval/harness /eval/harness
WORKDIR /eval
ENTRYPOINT ["python", "/eval/harness/run.py"]
