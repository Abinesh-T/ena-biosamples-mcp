"""MCP server exposing ENA and BioSamples data as tools for LLM clients."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from ena_mcp.config import settings
from ena_mcp.ena_service import EnaService, RecordCount, RecordType, create_http_client

# The stdio transport uses stdout for protocol messages, so logs must go to stderr.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

mcp = FastMCP(
    "ena-biosamples",
    instructions=(
        "Answer questions about public genomics data in the European Nucleotide Archive (ENA) "
        "and BioSamples. Species can be given by scientific or common name."
    ),
    host=settings.host,
    port=settings.port,
)


@asynccontextmanager
async def ena_service() -> AsyncIterator[EnaService]:
    async with create_http_client(settings.http_timeout_seconds) as client:
        yield EnaService(client, settings.ena_portal_url, settings.ena_taxonomy_url)


@mcp.tool()
async def count_records(
    species: str,
    record_type: RecordType = "read_run",
    include_subspecies: bool = True,
) -> RecordCount:
    """Count ENA records for a species.

    Args:
        species: Scientific or common name, e.g. "Bos taurus" or "cattle".
        record_type: "read_run" (sequencing runs), "sample", or "assembly".
        include_subspecies: Also count subspecies and breeds under this taxon.
    """
    async with ena_service() as service:
        return await service.count_records(species, record_type, include_subspecies)


def main() -> None:
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    main()
