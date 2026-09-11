"""Unit tests for BioSamplesService using a mock HTTP transport (no network)."""

import httpx
import pytest

from ena_mcp.biosamples_service import BioSamplesApiError, BioSamplesService

BASE = "https://biosamples.test/biosamples"

PAYLOAD = {
    "name": "cow-liver-01",
    "accession": "SAMEA0000001",
    "taxId": 9913,
    "release": "2022-01-10T00:00:00Z",
    "update": "2023-02-01T00:00:00Z",
    "characteristics": {
        "organism": [
            {"text": "Bos taurus", "ontologyTerms": ["http://purl.obolibrary.org/obo/NCBITaxon_9913"]}
        ],
        "collection date": [{"text": "2021-05-04"}],
        "scientific_name": [{"text": "Bos taurus", "ontologyTerms": [""]}],
        "age": [{"text": "24", "unit": "month"}],
        "tissue": [{"text": "liver"}, {"text": "kidney"}],
    },
}


async def fetch(handler, accession: str = "SAMEA0000001"):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await BioSamplesService(client, BASE).get_sample(accession)


@pytest.mark.anyio
async def test_sample_is_flattened_and_json_requested():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["accept"] = request.headers.get("accept")
        return httpx.Response(200, json=PAYLOAD)

    sample = await fetch(handler, accession=" sameA0000001 ")
    by_name = {c.name: c for c in sample.characteristics}

    assert seen["path"] == "/biosamples/samples/SAMEA0000001"
    assert seen["accept"] == "application/json"
    assert sample.tax_id == 9913
    assert by_name["organism"].ontology_terms[0].endswith("NCBITaxon_9913")
    assert by_name["age"].unit == "month"
    assert by_name["tissue"].value == "liver; kidney"
    assert by_name["scientific_name"].ontology_terms == []


@pytest.mark.anyio
@pytest.mark.parametrize("bad", ["ERR123456", "ERS000001", "12345", ""])
async def test_non_biosamples_accession_rejected_without_request(bad: str):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(BioSamplesApiError, match="not a BioSamples accession"):
        await fetch(handler, accession=bad)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 404])
async def test_missing_or_private_sample(status: int):
    with pytest.raises(BioSamplesApiError, match="not found or is not public"):
        await fetch(lambda request: httpx.Response(status))


@pytest.mark.anyio
async def test_server_error_raises():
    with pytest.raises(BioSamplesApiError, match="lookup failed"):
        await fetch(lambda request: httpx.Response(500, text="boom"))


@pytest.mark.anyio
async def test_network_error_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(BioSamplesApiError, match="Could not reach BioSamples"):
        await fetch(handler)
