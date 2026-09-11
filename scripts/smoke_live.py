"""Live check against the real ENA API.

Run: uv run python scripts/smoke_live.py
"""

import asyncio

from ena_mcp.config import settings
from ena_mcp.ena_service import EnaService, create_http_client


async def main() -> None:
    async with create_http_client(settings.http_timeout_seconds) as client:
        service = EnaService(client, settings.ena_portal_url, settings.ena_taxonomy_url)
        for record_type in ("read_run", "sample", "assembly"):
            result = await service.count_records("cattle", record_type)
            print(result.model_dump_json(indent=2))

        search = await service.search_samples("cattle", country="United Kingdom", limit=3)
        print(search.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
