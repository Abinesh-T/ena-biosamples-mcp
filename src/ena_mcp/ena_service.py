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

# ENA returns these columns for each sample; keys map 1:1 to SampleSummary fields.
SAMPLE_FIELDS: dict[str, str] = {
    "sample_accession": "accession",
    "scientific_name": "scientific_name",
    "country": "country",
    "collection_date": "collection_date",
    "first_public": "first_public",
    "center_name": "center_name",
    "description": "description",
}
MAX_SEARCH_LIMIT = 100

# Ranks above species: results then cover many species, which the client should know.
HIGHER_RANKS = {
    "subgenus", "genus", "tribe", "subfamily", "family", "superfamily",
    "order", "class", "phylum", "kingdom", "superkingdom", "domain",
}


class EnaApiError(Exception):
    """Raised when ENA is unreachable or returns an unexpected response."""


class Taxon(BaseModel):
    tax_id: str
    scientific_name: str
    common_name: str | None = None
    rank: str | None = None
    # Other taxa that matched the same name, e.g. "Bos (9903, genus)", so clients can clarify.
    other_matches: list[str] = []
    note: str | None = None


class RecordCount(BaseModel):
    taxon: Taxon
    record_type: RecordType
    count: int
    include_subspecies: bool
    query: str


class SampleSummary(BaseModel):
    accession: str
    scientific_name: str | None = None
    country: str | None = None
    collection_date: str | None = None
    first_public: str | None = None
    center_name: str | None = None
    description: str | None = None


class SampleSearchResult(BaseModel):
    taxon: Taxon
    country_filter: str | None
    total_matching: int
    returned: int
    samples: list[SampleSummary]
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

        best = _pick_best_taxon(name, matches)
        others = [m for m in matches if m is not best]
        if others:
            logger.info("Multiple taxa matched", extra={"name": name, "chosen": best["taxId"]})
        return Taxon(
            tax_id=str(best["taxId"]),
            scientific_name=best["scientificName"],
            common_name=best.get("commonName"),
            rank=best.get("rank"),
            other_matches=[
                f"{m['scientificName']} ({m['taxId']}, {m.get('rank') or 'unranked'})" for m in others
            ],
            note=_rank_note(best),
        )

    async def count_records(
        self,
        species: str,
        record_type: RecordType = "read_run",
        include_subspecies: bool = True,
    ) -> RecordCount:
        """Count ENA records of one type for a species."""
        taxon = await self.resolve_taxon(species)
        query = _taxon_query(taxon.tax_id, include_subspecies)
        return RecordCount(
            taxon=taxon,
            record_type=record_type,
            count=await self._count(record_type, query),
            include_subspecies=include_subspecies,
            query=query,
        )

    async def search_samples(
        self,
        species: str,
        country: str | None = None,
        limit: int = 20,
        include_subspecies: bool = True,
    ) -> SampleSearchResult:
        """Find samples for a species, optionally filtered by country.

        Args:
            species: Scientific or common name.
            country: Country name, e.g. "United Kingdom". Exact, case-insensitive match.
            limit: Max samples to return (1-100). The total match count is always returned.
            include_subspecies: Include subspecies and breeds under the taxon.

        Returns:
            Total matching samples plus up to `limit` sample records.
        """
        taxon = await self.resolve_taxon(species)
        country_filter = _clean_country(country)
        query = _taxon_query(taxon.tax_id, include_subspecies)
        if country_filter:
            # Exact match on purpose: live ENA returns 0 for a trailing wildcard on multi-word
            # values ('country="United Kingdom*"') but 5,188 cattle samples for the exact name.
            query += f' AND country="{country_filter}"'

        page_size = max(1, min(limit, MAX_SEARCH_LIMIT))
        response = await self._get(
            f"{self._portal_url}/search",
            params={
                "result": "sample",
                "query": query,
                "fields": ",".join(SAMPLE_FIELDS),
                "limit": str(page_size),
                "format": "json",
            },
        )
        if response.status_code not in (200, 204):
            raise EnaApiError(
                f"ENA sample search failed ({response.status_code}): {response.text[:200]}"
            )

        samples = [_to_sample(row) for row in _json_rows(response)]
        # The page is capped, so tell the client how many samples exist in total.
        total = await self._count("sample", query)
        return SampleSearchResult(
            taxon=taxon,
            country_filter=country_filter,
            total_matching=total,
            returned=len(samples),
            samples=samples,
            query=query,
        )

    async def _count(self, result: str, query: str) -> int:
        response = await self._get(
            f"{self._portal_url}/count", params={"result": result, "query": query}
        )
        if response.status_code != 200:
            raise EnaApiError(
                f"ENA count failed ({response.status_code}): {response.text[:200]}"
            )
        return _parse_count(response.text)

    async def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        try:
            return await self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning("ENA request failed", extra={"url": url, "error": str(exc)})
            raise EnaApiError(f"Could not reach ENA: {exc}") from exc


def _pick_best_taxon(name: str, matches: list[dict]) -> dict:
    """Choose the taxon a researcher most likely means.

    Common names are ambiguous: "cattle" matches both the genus Bos and the species
    Bos taurus, and ENA may list the genus first. Prefer an exact scientific-name match,
    then a species, then ENA's own ordering.
    """
    lowered = name.lower()
    exact = [m for m in matches if str(m.get("scientificName", "")).lower() == lowered]
    if exact:
        return exact[0]
    species = [m for m in matches if m.get("rank") == "species"]
    return species[0] if species else matches[0]


def _rank_note(match: dict) -> str | None:
    rank = match.get("rank")
    if rank not in HIGHER_RANKS:
        return None
    # e.g. ENA resolves "cattle" to the genus Bos, which also covers yak, zebu and gaur.
    return (
        f"'{match['scientificName']}' is a {rank}, so results include every species under it. "
        "Use a species name (e.g. 'Bos taurus') to narrow down."
    )


def _taxon_query(tax_id: str, include_subspecies: bool) -> str:
    # tax_tree also matches subspecies and breeds registered under the taxon; tax_eq is exact.
    operator = "tax_tree" if include_subspecies else "tax_eq"
    return f"{operator}({tax_id})"


def _clean_country(country: str | None) -> str | None:
    """Strip characters that would break out of the quoted ENA query value."""
    if country is None:
        return None
    cleaned = country.replace('"', "").replace("*", "").strip()
    return cleaned or None


def _json_rows(response: httpx.Response) -> list[dict]:
    # ENA sends an empty body (sometimes 204) when nothing matches.
    if response.status_code == 204 or not response.text.strip():
        return []
    try:
        rows = response.json()
    except ValueError as exc:
        raise EnaApiError(f"Unexpected search response from ENA: {response.text[:100]}") from exc
    if not isinstance(rows, list):
        raise EnaApiError("Unexpected search response from ENA: expected a list.")
    return rows


def _to_sample(row: dict) -> SampleSummary:
    # ENA uses "" for missing values; normalise to None so clients see real gaps.
    values = {model_key: (row.get(ena_key) or None) for ena_key, model_key in SAMPLE_FIELDS.items()}
    values["accession"] = values["accession"] or ""
    return SampleSummary(**values)


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
