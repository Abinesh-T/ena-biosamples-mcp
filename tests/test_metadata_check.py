"""Unit tests for the pure metadata completeness rules."""

import pytest

from ena_mcp.biosamples_service import BioSample, Characteristic
from ena_mcp.metadata_check import check_metadata


def sample(**attributes: str) -> BioSample:
    return BioSample(
        accession="SAMEA0000001",
        characteristics=[Characteristic(name=k, value=v) for k, v in attributes.items()],
    )


COMPLETE = {
    "organism": "Bos taurus",
    "collection date": "2021-05-04",
    "geographic location (country and/or sea)": "United Kingdom",
}


def status_of(report, field: str) -> str:
    return next(c.status for c in report.fields if c.field == field)


def test_complete_sample_passes():
    report = check_metadata(sample(**COMPLETE))
    assert report.passed
    assert report.summary.startswith("All 3 required fields")


def test_absent_field_fails():
    attrs = {k: v for k, v in COMPLETE.items() if k != "collection date"}
    report = check_metadata(sample(**attrs))

    assert not report.passed
    assert status_of(report, "collection date") == "absent"
    assert "collection date (absent)" in report.summary


@pytest.mark.parametrize("term", ["not collected", "missing: control sample", "Restricted access"])
def test_insdc_missing_value_terms_are_declared_missing(term: str):
    report = check_metadata(sample(**{**COMPLETE, "geographic location (country and/or sea)": term}))
    assert status_of(report, "geographic location (country and/or sea)") == "declared_missing"


@pytest.mark.parametrize("date", ["2021", "2021-05", "2019-05/2019-06", "2021-05-04T10:30:00Z"])
def test_valid_iso_dates(date: str):
    report = check_metadata(sample(**{**COMPLETE, "collection date": date}))
    assert status_of(report, "collection date") == "ok"


@pytest.mark.parametrize("date", ["May 2021", "04/05/2021", "2021-5-4"])
def test_invalid_dates(date: str):
    report = check_metadata(sample(**{**COMPLETE, "collection date": date}))
    assert status_of(report, "collection date") == "invalid_format"


def test_alias_and_underscore_names_are_recognised():
    attrs = {
        "Organism": "Bos taurus",
        "collection_date": "2021",
        "geo_loc_name": "Kenya:Nairobi",
    }
    assert check_metadata(sample(**attrs)).passed


def test_extra_fields_are_required_and_not_duplicated():
    report = check_metadata(sample(**COMPLETE, sex="female"), extra_fields=["sex", "breed", "Organism", " "])

    assert [c.field for c in report.fields][-2:] == ["sex", "breed"]
    assert len(report.fields) == 5
    assert status_of(report, "sex") == "ok"
    assert status_of(report, "breed") == "absent"
