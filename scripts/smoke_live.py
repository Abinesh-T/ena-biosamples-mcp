"""Live check against the real ENA API.

Run: uv run python scripts/smoke_live.py
"""

import asyncio

from ena_mcp.biosamples_service import BioSamplesService
from ena_mcp.config import settings
from ena_mcp.ena_service import EnaService, create_http_client
from ena_mcp.metadata_check import check_metadata


async def main() -> None:
    async with create_http_client(settings.http_timeout_seconds) as client:
        service = EnaService(client, settings.ena_portal_url, settings.ena_taxonomy_url)
        for record_type in ("read_run", "sample", "assembly"):
            result = await service.count_records("Bos taurus", record_type)
            print(result.model_dump_json(indent=2))

        cattle = await service.resolve_taxon("cattle")
        print(cattle.model_dump_json(indent=2))

        search = await service.search_samples("Bos taurus", country="United Kingdom", limit=3)
        print(search.model_dump_json(indent=2))

        if not search.samples:
            print("No samples returned; skipping BioSamples check.")
            return
        biosamples = BioSamplesService(client, settings.biosamples_url)
        sample = await biosamples.get_sample(search.samples[0].accession)
        print(sample.model_dump_json(indent=2))
        print(check_metadata(sample, ["sex", "breed"]).model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
