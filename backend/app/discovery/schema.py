"""DatasetRecord: one normalized shape for curated packs, seeded records and imported provider metadata.

Every consequential claim (formats, access, license, coverage, each field) carries:
    status   - "verified"          checked by this project (pack loader/tests ran against the data)
             - "provider-reported" stated by the publisher, with an evidence URL
             - "unknown"           not established - the UI says so instead of guessing
    evidence - URL or repo path backing the claim (may be null for unknown)
    note     - optional human explanation
Unknown values stay explicit (null / "unknown"); nothing is silently defaulted.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["verified", "provider-reported", "unknown"]
CONCEPTS = ("latlon", "timestamp", "target_label", "join_key", "geo_boundary")


class Claim(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Status = "unknown"
    evidence: str | None = None
    note: str | None = None


class Formats(Claim):
    values: list[str] = Field(default_factory=list)
    exhaustive: bool = True  # False: other formats may exist but weren't checked


class Access(Claim):
    method: Literal["direct-download", "api", "sign-in", "request", "unknown"] = "unknown"
    signInRequired: bool | None = None


class License(Claim):
    name: str | None = None
    url: str | None = None
    commercialUse: Literal["allowed", "not-allowed", "conditional", "unknown"] = "unknown"


class Temporal(Claim):
    start: str | None = None
    end: str | None = None
    ongoing: bool | None = None
    granularity: list[str] = Field(default_factory=list)
    dependsOnRequest: bool = False


class Spatial(Claim):
    scope: str = "unknown"  # city | country | global-point-query | global-grid | point-station | not-applicable | unknown
    regions: list[str] = Field(default_factory=list)
    description: str | None = None


class Coverage(BaseModel):
    temporal: Temporal = Field(default_factory=Temporal)
    spatial: Spatial = Field(default_factory=Spatial)


class DataField(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    type: str | None = None
    unit: str | None = None
    description: str = ""
    concepts: list[str] = Field(default_factory=list)
    # record: a value on every row/event; input: an API request parameter; grid: grid-cell coordinate
    level: Literal["record", "input", "grid", "derived"] = "record"
    status: Status = "provider-reported"
    evidence: str | None = None
    configs: list[str] = Field(default_factory=list)  # Hugging Face subsets that contain this field


class Link(BaseModel):
    label: str
    url: str


class DataFile(BaseModel):
    """A downloadable file the user can preview or import on demand (never fetched during search)."""
    model_config = ConfigDict(extra="allow")
    url: str
    name: str | None = None
    format: str | None = None
    bytes: int | None = None
    config: str | None = None
    split: str | None = None


class Size(BaseModel):
    rows: int | None = None
    bytes: int | None = None
    note: str | None = None


class DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,120}$")
    title: str
    description: str
    publisher: str
    provider: str
    providerId: str
    canonicalUrl: str = Field(pattern=r"^https://")
    sourceLinks: list[Link] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    characteristics: list[str] = Field(default_factory=list)
    formats: Formats = Field(default_factory=Formats)
    access: Access = Field(default_factory=Access)
    license: License = Field(default_factory=License)
    coverage: Coverage = Field(default_factory=Coverage)
    schemaStatus: Literal["complete", "partial", "unknown"] = "unknown"
    fields: list[DataField] = Field(default_factory=list)
    size: Size = Field(default_factory=Size)
    limitations: list[str] = Field(default_factory=list)
    sourceUpdatedAt: str | None = None
    lastVerifiedAt: str | None = None
    lastFetchedAt: str | None = None
    origin: Literal["pack", "seed", "import", "live"] = "import"
    reviewStatus: Literal["reviewed", "unreviewed"] = "unreviewed"
    packId: str | None = None
    kind: Literal["dataset", "documentation"] = "dataset"  # documentation: the source itself says it's a report/PDF
    doi: str | None = None
    unitOfAnalysis: str | None = None
    files: list[DataFile] = Field(default_factory=list)
    previewProvider: str | None = None  # e.g. "huggingface" when a row preview API exists
    configs: list[str] = Field(default_factory=list)


def normalize(raw: dict) -> dict:
    """Validate and fill defaults. Raises pydantic.ValidationError on bad records."""
    return DatasetRecord.model_validate(raw).model_dump(mode="json")
