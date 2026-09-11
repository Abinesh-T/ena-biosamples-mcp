"""Service layer for the ENA Portal and Taxonomy APIs.

All HTTP access to ENA lives here so the MCP tools stay thin and tests can
swap in a mock transport.
"""

import json
import logging
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

RecordType = Literal["read_run", "sample", "assembly"]

USER_AGENT = "ena-biosamples-mcp/0.1 (+https://github.com/Abinesh-T/ena-biosamples-mcp)"


class EnaApiError(Exception):
    """Raised when ENA is unreachable or returns an unexpected response."""


class Taxon(BaseModel):
    tax_id: str
    scientific_name: str
    common_name: str | None = None
    rank: str | None = None


class RecordCount(BaseModel):
    taxon: Taxon
    record_type: RecordType
    count: int
    include_subspecies: bool
    query: str


def create_http_client(timeout_seconds: float) -> httpx.AsyncClient:
    """Build the shared HTTP client with a descriptive User-Agent for EBI's logs."""
    return httpx.AsyncClient(timeout=timeout_seconds, headers={"User-Agent": USER_AGENT})


class EnaService:
    def __init__(self, client: httpx.AsyncClient, portal_url: str, taxonomy_url: str) -> None:
        self._client = client
        self._portal_url = portal_url.rstrip("/")
        self._taxonomy_url = taxonomy_url.rstrip("/")

    async def resolve_taxon(self, species: str) -> Taxon:
        """Resolve a scientific or common name to an NCBI taxon.

        Args:
            species: e.g. "Bos taurus" or "cattle".

        Returns:
            The first matching taxon.
        """
        name = species.strip()
        if not name:
            raise EnaApiError("Species name is empty.")

        # any-name matches scientific AND common names, so researchers can ask in plain language.
        response = await self._get(f"{self._taxonomy_url}/any-name/{quote(name)}")
        if response.status_code == 404:
            raise EnaApiError(f"No taxon found for '{name}'.")
        if response.status_code != 200:
            raise EnaApiError(f"ENA taxonomy lookup failed ({response.status_code}).")

        try:
            matches = response.json()
        except ValueError:
            # ENA answers some misses with a plain-text body instead of JSON.
            raise EnaApiError(f"No taxon found for '{name}'.") from None
        if not isinstance(matches, list) or not matches:
            raise EnaApiError(f"No taxon found for '{name}'.")

        if len(matches) > 1:
            logger.info("Multiple taxa matched; using the first", extra={"name": name})
        first = matches[0]
        return Taxon(
            tax_id=str(first["taxId"]),
            scientific_name=first["scientificName"],
            common_name=first.get("commonName"),
            rank=first.get("rank"),
        )

    async def count_records(
        self,
        species: str,
        record_type: RecordType = "read_run",
        include_subspecies: bool = True,
    ) -> RecordCount:
        """Count ENA records of one type for a species."""
        taxon = await self.resolve_taxon(species)

        # tax_tree also counts subspecies and breeds registered under the taxon; tax_eq is exact.
        operator = "tax_tree" if include_subspecies else "tax_eq"
        query = f"{operator}({taxon.tax_id})"
        response = await self._get(
            f"{self._portal_url}/count", params={"result": record_type, "query": query}
        )
        if response.status_code != 200:
            raise EnaApiError(
                f"ENA count failed ({response.status_code}): {response.text[:200]}"
            )

        return RecordCount(
            taxon=taxon,
            record_type=record_type,
            count=_parse_count(response.text),
            include_subspecies=include_subspecies,
            query=query,
        )

    async def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        try:
            return await self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning("ENA request failed", extra={"url": url, "error": str(exc)})
            raise EnaApiError(f"Could not reach ENA: {exc}") from exc


def _parse_count(body: str) -> int:
    """Parse the ENA count response.

    ENA returns TSV with a header line ("count\\n143292"). Plain digits and JSON are
    also accepted so a format change on ENA's side doesn't break the tool.
    """
    text = body.strip()
    last_line = text.splitlines()[-1].strip() if text else ""
    if last_line.isdigit():
        return int(last_line)
    try:
        return int(json.loads(text)["count"])
    except (ValueError, KeyError, TypeError) as exc:
        raise EnaApiError(f"Unexpected count response from ENA: {text[:100]}") from exc
