"""Unit tests for EnaService using a mock HTTP transport (no network)."""

from collections.abc import Callable

import httpx
import pytest

from ena_mcp.ena_service import EnaApiError, EnaService

PORTAL = "https://ena.test/portal/api"
TAXONOMY = "https://ena.test/taxonomy/rest"
CATTLE = [{"taxId": "9913", "scientificName": "Bos taurus", "commonName": "cattle", "rank": "species"}]

Handler = Callable[[httpx.Request], httpx.Response]


async def run_count(handler: Handler, species: str = "cattle", **kwargs):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await EnaService(client, PORTAL, TAXONOMY).count_records(species, **kwargs)


def taxonomy_then(count_response: httpx.Response, seen: dict) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/taxonomy/rest/any-name/"):
            seen["taxonomy_path"] = request.url.path
            return httpx.Response(200, json=CATTLE)
        seen["count_params"] = dict(request.url.params)
        return count_response

    return handler


@pytest.mark.anyio
async def test_common_name_resolves_and_counts_with_tax_tree():
    seen: dict = {}
    # Real ENA format: TSV with a header line.
    result = await run_count(taxonomy_then(httpx.Response(200, text="count\n4821\n"), seen))

    assert result.count == 4821
    assert result.taxon.tax_id == "9913"
    assert seen["taxonomy_path"] == "/taxonomy/rest/any-name/cattle"
    assert seen["count_params"] == {"result": "read_run", "query": "tax_tree(9913)"}


@pytest.mark.anyio
async def test_exact_taxon_uses_tax_eq():
    seen: dict = {}
    result = await run_count(
        taxonomy_then(httpx.Response(200, text="12"), seen),
        record_type="assembly",
        include_subspecies=False,
    )

    assert result.query == "tax_eq(9913)"
    assert seen["count_params"]["result"] == "assembly"


@pytest.mark.anyio
async def test_plain_digit_count_body_is_accepted():
    result = await run_count(taxonomy_then(httpx.Response(200, text="143292"), {}))
    assert result.count == 143292


@pytest.mark.anyio
async def test_json_count_body_is_accepted():
    result = await run_count(taxonomy_then(httpx.Response(200, json={"count": 7}), {}))
    assert result.count == 7


@pytest.mark.anyio
@pytest.mark.parametrize(
    "taxonomy_response",
    [httpx.Response(404), httpx.Response(200, text="No results."), httpx.Response(200, json=[])],
)
async def test_unknown_species_raises(taxonomy_response: httpx.Response):
    with pytest.raises(EnaApiError, match="No taxon found"):
        await run_count(lambda request: taxonomy_response, species="unicorn")


@pytest.mark.anyio
async def test_empty_species_raises_before_any_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(EnaApiError, match="empty"):
        await run_count(handler, species="   ")


@pytest.mark.anyio
async def test_ena_server_error_raises():
    with pytest.raises(EnaApiError, match="count failed"):
        await run_count(taxonomy_then(httpx.Response(500, text="boom"), {}))


@pytest.mark.anyio
async def test_network_error_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(EnaApiError, match="Could not reach ENA"):
        await run_count(handler)


GENUS_FIRST = [
    {"taxId": "9903", "scientificName": "Bos", "commonName": "cattle", "rank": "genus"},
    {"taxId": "9913", "scientificName": "Bos taurus", "commonName": "cattle", "rank": "species"},
]


async def resolve(matches: list[dict], name: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=matches)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await EnaService(client, PORTAL, TAXONOMY).resolve_taxon(name)


@pytest.mark.anyio
async def test_common_name_prefers_species_over_genus():
    # Regression: live ENA resolved "cattle" to the genus Bos (9903) instead of Bos taurus.
    taxon = await resolve(GENUS_FIRST, "cattle")

    assert taxon.tax_id == "9913"
    assert taxon.other_matches == ["Bos (9903, genus)"]


@pytest.mark.anyio
async def test_exact_scientific_name_wins_even_for_genus():
    taxon = await resolve(GENUS_FIRST, "bos")
    assert taxon.tax_id == "9903"
    assert taxon.other_matches == ["Bos taurus (9913, species)"]


@pytest.mark.anyio
async def test_genus_match_carries_a_note_but_species_does_not():
    # Live ENA resolves "cattle" to the genus Bos only, so the client must be told.
    genus = await resolve([GENUS_FIRST[0]], "cattle")
    species = await resolve([GENUS_FIRST[1]], "Bos taurus")

    assert genus.note is not None and "genus" in genus.note
    assert species.note is None
