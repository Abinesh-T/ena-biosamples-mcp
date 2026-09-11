"""Metadata completeness checks for BioSamples records.

Pure functions (no I/O) so the rules are easy to test and extend with
consortium-specific requirements such as FAANG or ERGA checklists.
"""

import re
from typing import Literal

from pydantic import BaseModel

from ena_mcp.biosamples_service import BioSample

# Fields ENA requires on every sample. Keys are the canonical names; aliases cover
# records imported from NCBI or submitted with underscore-style names.
CORE_FIELDS: dict[str, tuple[str, ...]] = {
    "organism": ("organism",),
    "collection date": ("collection date",),
    "geographic location (country and/or sea)": (
        "geographic location (country and/or sea)",
        "geo loc name",
        "geographic location",
    ),
}

# INSDC "missing value" vocabulary: the submitter consciously declared the value unavailable.
DECLARED_MISSING_PREFIXES = (
    "missing",
    "not applicable",
    "not collected",
    "not provided",
    "restricted access",
)

# ISO 8601 date, truncated date, or interval: 2021, 2021-05, 2021-05-04, 2021-05-04T10:00:00Z,
# 2019-05/2019-06.
_ISO_PART = r"\d{4}(-\d{2}(-\d{2}(T\d{2}(:\d{2}(:\d{2})?)?Z?)?)?)?"
ISO_DATE_PATTERN = re.compile(rf"^{_ISO_PART}(/{_ISO_PART})?$")

FieldStatus = Literal["ok", "absent", "declared_missing", "invalid_format"]


class FieldCheck(BaseModel):
    field: str
    status: FieldStatus
    value: str | None = None
    note: str | None = None


class MetadataReport(BaseModel):
    accession: str
    passed: bool
    fields: list[FieldCheck]
    summary: str


def check_metadata(sample: BioSample, extra_fields: list[str] | None = None) -> MetadataReport:
    """Check a sample against the core ENA fields plus any caller-supplied fields.

    Args:
        sample: The BioSamples record.
        extra_fields: Additional required attribute names, e.g. ["sex", "breed"] for FAANG.

    Returns:
        A per-field report. `passed` is True only when every field is "ok".
    """
    values = {_normalise(c.name): c.value for c in sample.characteristics}

    requirements = dict(CORE_FIELDS)
    for name in extra_fields or []:
        cleaned = name.strip()
        if cleaned and _normalise(cleaned) not in {_normalise(k) for k in requirements}:
            requirements[cleaned] = (cleaned,)

    checks = [_check_field(field, aliases, values) for field, aliases in requirements.items()]
    problems = [c for c in checks if c.status != "ok"]
    summary = (
        f"All {len(checks)} required fields are present and valid."
        if not problems
        else f"{len(problems)} of {len(checks)} required fields need attention: "
        + ", ".join(f"{c.field} ({c.status})" for c in problems)
    )
    return MetadataReport(
        accession=sample.accession, passed=not problems, fields=checks, summary=summary
    )


def _check_field(field: str, aliases: tuple[str, ...], values: dict[str, str]) -> FieldCheck:
    value = next((values[_normalise(a)] for a in aliases if values.get(_normalise(a))), None)
    if value is None:
        return FieldCheck(field=field, status="absent")

    if value.lower().startswith(DECLARED_MISSING_PREFIXES):
        return FieldCheck(
            field=field,
            status="declared_missing",
            value=value,
            note="Submitter used an INSDC missing-value term.",
        )

    if field == "collection date" and not ISO_DATE_PATTERN.match(value):
        return FieldCheck(
            field=field,
            status="invalid_format",
            value=value,
            note="Expected ISO 8601, e.g. 2021, 2021-05 or 2021-05-04.",
        )

    return FieldCheck(field=field, status="ok", value=value)


def _normalise(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())
