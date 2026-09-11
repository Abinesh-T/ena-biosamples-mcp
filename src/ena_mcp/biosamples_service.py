"""Service layer for the EBI BioSamples API.

All HTTP access to BioSamples lives here so MCP tools stay thin and tests can
swap in a mock transport.
"""

import logging
import re
from urllib.parse import quote

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# BioSamples accessions: SAMEA..., SAMN..., SAMD..., SAMEG... followed by digits.
ACCESSION_PATTERN = re.compile(r"^SAM[A-Z]{0,2}\d+$")


class BioSamplesApiError(Exception):
    """Raised when BioSamples is unreachable, the accession is invalid, or the sample is missing."""


class Characteristic(BaseModel):
    name: str
    value: str
    unit: str | None = None
    ontology_terms: list[str] = []


class BioSample(BaseModel):
    accession: str
    name: str | None = None
    tax_id: int | None = None
    release_date: str | None = None
    update_date: str | None = None
    characteristics: list[Characteristic]


class BioSamplesService:
    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def get_sample(self, accession: str) -> BioSample:
        """Fetch one sample and flatten its characteristics.

        Args:
            accession: BioSamples accession, e.g. "SAMEA7658521".

        Returns:
            The sample with one Characteristic per attribute.
        """
        normalised = accession.strip().upper()
        if not ACCESSION_PATTERN.match(normalised):
            raise BioSamplesApiError(
                f"'{accession}' is not a BioSamples accession (expected e.g. SAMEA123456). "
                "ENA run or experiment accessions are not accepted here."
            )

        url = f"{self._base_url}/samples/{quote(normalised)}"
        try:
            response = await self._client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            logger.warning("BioSamples request failed", extra={"url": url, "error": str(exc)})
            raise BioSamplesApiError(f"Could not reach BioSamples: {exc}") from exc

        if response.status_code in (403, 404):
            # Private samples come back as 403; to a caller both mean "not publicly available".
            raise BioSamplesApiError(f"Sample {normalised} was not found or is not public.")
        if response.status_code != 200:
            raise BioSamplesApiError(
                f"BioSamples lookup failed ({response.status_code}): {response.text[:200]}"
            )

        try:
            return _to_biosample(response.json())
        except (ValueError, KeyError, TypeError) as exc:
            raise BioSamplesApiError(f"Unexpected response from BioSamples for {normalised}.") from exc


def _to_biosample(payload: dict) -> BioSample:
    characteristics = []
    for name, entries in (payload.get("characteristics") or {}).items():
        # One attribute can hold several values; join them so clients see a single string.
        texts = [str(entry.get("text", "")).strip() for entry in entries]
        # Live records sometimes carry empty ontology terms ([""]); drop them.
        terms = [term for entry in entries for term in (entry.get("ontologyTerms") or []) if term]
        units = [entry["unit"] for entry in entries if entry.get("unit")]
        characteristics.append(
            Characteristic(
                name=name,
                value="; ".join(text for text in texts if text),
                unit=units[0] if units else None,
                ontology_terms=terms,
            )
        )

    return BioSample(
        accession=payload["accession"],
        name=payload.get("name"),
        tax_id=payload.get("taxId"),
        release_date=payload.get("release"),
        update_date=payload.get("update"),
        characteristics=characteristics,
    )
