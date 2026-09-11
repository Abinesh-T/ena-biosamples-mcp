FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install locked dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Inside a container the server is reached over Streamable HTTP at /mcp, so bind to all
# interfaces. (The MCP SDK only enables DNS-rebinding protection for localhost binds.)
ENV PATH="/app/.venv/bin:$PATH" \
    ENA_MCP_TRANSPORT=streamable-http \
    ENA_MCP_HOST=0.0.0.0 \
    ENA_MCP_PORT=8000

RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000
CMD ["ena-mcp"]
