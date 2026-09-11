"""MCP server exposing ENA and BioSamples data as tools for LLM clients."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from ena_mcp.biosamples_service import BioSample, BioSamplesService
from ena_mcp.config import settings
from ena_mcp.ena_service import (
    EnaService,
    RecordCount,
    RecordType,
    SampleSearchResult,
    create_http_client,
)
from ena_mcp.metadata_check import MetadataReport, check_metadata

# The stdio transport uses stdout for protocol messages, so logs must go to stderr.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

mcp = FastMCP(
    "ena-biosamples",
    instructions=(
        "Tools for EMBL-EBI public genomics data: the European Nucleotide Archive (ENA) and "
        "BioSamples. Use them for any question about sequencing runs, samples, assemblies, "
        "sample metadata or species counts in ENA/BioSamples, instead of browsing or fetching "
        "ebi.ac.uk URLs. Species can be given by scientific or common name; if a result carries "
        "a taxon note (e.g. a genus match), tell the user and suggest a species name."
    ),
    host=settings.host,
    port=settings.port,
)


@asynccontextmanager
async def ena_service() -> AsyncIterator[EnaService]:
    async with create_http_client(settings.http_timeout_seconds) as client:
        yield EnaService(client, settings.ena_portal_url, settings.ena_taxonomy_url)


@asynccontextmanager
async def biosamples_service() -> AsyncIterator[BioSamplesService]:
    async with create_http_client(settings.http_timeout_seconds) as client:
        yield BioSamplesService(client, settings.biosamples_url)


@mcp.tool()
async def count_records(
    species: str,
    record_type: RecordType = "read_run",
    include_subspecies: bool = True,
) -> RecordCount:
    """Count records for a species in the European Nucleotide Archive (ENA, EMBL-EBI).

    Args:
        species: Scientific or common name, e.g. "Bos taurus" or "cattle".
        record_type: "read_run" (sequencing runs), "sample", or "assembly".
        include_subspecies: Also count subspecies and breeds under this taxon.
    """
    async with ena_service() as service:
        return await service.count_records(species, record_type, include_subspecies)



@mcp.tool()
async def search_samples(
    species: str,
    country: str | None = None,
    limit: int = 20,
    include_subspecies: bool = True,
) -> SampleSearchResult:
    """Find samples in the European Nucleotide Archive (ENA, EMBL-EBI) for a species.

    Optionally filter by country of origin.

    Returns the total number of matching samples plus up to `limit` records with
    accession, country, collection date, first public date, submitting centre and description.

    Args:
        species: Scientific or common name, e.g. "Bos taurus" or "cattle".
        country: Country name, e.g. "United Kingdom" or "Kenya". Omit for all countries.
        limit: Max samples to return (1-100). Default 20.
        include_subspecies: Also include subspecies and breeds under this taxon.
    """
    async with ena_service() as service:
        return await service.search_samples(species, country, limit, include_subspecies)


@mcp.tool()
async def get_biosample(accession: str) -> BioSample:
    """Get an EMBL-EBI BioSamples record with all its attributes.

    Attributes include organism, geographic location, tissue, breed and sex where submitted.

    Args:
        accession: BioSamples accession, e.g. "SAMEA7658521". Use the accession returned
            by search_samples.
    """
    async with biosamples_service() as service:
        return await service.get_sample(accession)


@mcp.tool()
async def check_sample_metadata(
    accession: str,
    extra_fields: list[str] | None = None,
) -> MetadataReport:
    """Check whether an ENA/BioSamples sample's metadata is complete and well-formed.

    Always checks the fields ENA requires on every sample (organism, collection date,
    geographic location). Flags fields that are absent, filled with an INSDC missing-value
    term (e.g. "not collected"), or badly formatted (collection date not ISO 8601).

    Args:
        accession: BioSamples accession, e.g. "SAMEA7658521".
        extra_fields: Additional attributes to require, e.g. ["sex", "breed", "tissue"]
            for a livestock (FAANG-style) project.
    """
    async with biosamples_service() as service:
        sample = await service.get_sample(accession)
    return check_metadata(sample, extra_fields)

def main() -> None:
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    main()
