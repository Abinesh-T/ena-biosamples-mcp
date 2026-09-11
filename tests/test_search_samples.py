"""Unit tests for EnaService.search_samples using a mock HTTP transport (no network)."""

import httpx
import pytest

from ena_mcp.ena_service import EnaApiError, EnaService

PORTAL = "https://ena.test/portal/api"
TAXONOMY = "https://ena.test/taxonomy/rest"
CATTLE = [{"taxId": "9913", "scientificName": "Bos taurus", "commonName": "cattle"}]

ROWS = [
    {
        "sample_accession": "SAMEA0000001",
        "scientific_name": "Bos taurus",
        "country": "United Kingdom:Hinxton",
        "collection_date": "2021-05-04",
        "first_public": "2022-01-10",
        "center_name": "EMBL-EBI",
        "description": "",
    },
    {
        "sample_accession": "SAMEA0000002",
        "scientific_name": "Bos taurus",
        "country": "",
        "collection_date": "",
        "first_public": "2023-03-01",
        "center_name": "",
        "description": "Liver tissue",
    },
]


class FakeEna:
    """Routes mock requests to taxonomy, search and count endpoints and records what was sent."""

    def __init__(self, search: httpx.Response, count_text: str = "count\n2\n") -> None:
        self.search_response = search
        self.count_text = count_text
        self.search_params: dict[str, str] = {}
        self.count_params: dict[str, str] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/taxonomy/rest/any-name/"):
            return httpx.Response(200, json=CATTLE)
        if path == "/portal/api/search":
            self.search_params = dict(request.url.params)
            return self.search_response
        if path == "/portal/api/count":
            self.count_params = dict(request.url.params)
            return httpx.Response(200, text=self.count_text)
        raise AssertionError(f"Unexpected request: {request.url}")


async def search(fake: FakeEna, **kwargs):
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        return await EnaService(client, PORTAL, TAXONOMY).search_samples("cattle", **kwargs)


@pytest.mark.anyio
async def test_country_filter_builds_prefix_query_and_counts_same_query():
    fake = FakeEna(httpx.Response(200, json=ROWS), count_text="count\n5120\n")
    result = await search(fake, country="United Kingdom", limit=2)

    expected_query = 'tax_tree(9913) AND country="United Kingdom*"'
    assert fake.search_params["query"] == expected_query
    assert fake.search_params["result"] == "sample"
    assert fake.search_params["format"] == "json"
    assert fake.search_params["limit"] == "2"
    assert "sample_accession" in fake.search_params["fields"].split(",")
    assert fake.count_params == {"result": "sample", "query": expected_query}
    assert result.total_matching == 5120
    assert result.returned == 2


@pytest.mark.anyio
async def test_empty_ena_values_become_none():
    result = await search(FakeEna(httpx.Response(200, json=ROWS)))

    first, second = result.samples
    assert first.accession == "SAMEA0000001"
    assert first.country == "United Kingdom:Hinxton"
    assert first.description is None
    assert second.country is None
    assert second.collection_date is None


@pytest.mark.anyio
async def test_no_country_means_taxon_only_query():
    fake = FakeEna(httpx.Response(200, json=ROWS))
    result = await search(fake, include_subspecies=False)

    assert fake.search_params["query"] == "tax_eq(9913)"
    assert result.country_filter is None


@pytest.mark.anyio
async def test_quotes_and_wildcards_are_stripped_from_country():
    fake = FakeEna(httpx.Response(200, json=[]))
    await search(fake, country='Kenya" OR tax_eq(1)*')

    assert fake.search_params["query"] == 'tax_tree(9913) AND country="Kenya OR tax_eq(1)*"'


@pytest.mark.anyio
@pytest.mark.parametrize(("requested", "sent"), [(500, "100"), (0, "1"), (-5, "1")])
async def test_limit_is_clamped(requested: int, sent: str):
    fake = FakeEna(httpx.Response(200, json=[]))
    await search(fake, limit=requested)
    assert fake.search_params["limit"] == sent


@pytest.mark.anyio
@pytest.mark.parametrize("empty", [httpx.Response(204), httpx.Response(200, text="")])
async def test_no_matches_returns_empty_list(empty: httpx.Response):
    result = await search(FakeEna(empty, count_text="count\n0\n"))
    assert result.samples == []
    assert result.total_matching == 0


@pytest.mark.anyio
async def test_invalid_request_surfaces_ena_message():
    fake = FakeEna(httpx.Response(400, text="Invalid field(s) provided: 'foo'"))
    with pytest.raises(EnaApiError, match="Invalid field"):
        await search(fake)
