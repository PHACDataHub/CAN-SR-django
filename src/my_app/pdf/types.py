from typing import Any

from django.core.exceptions import ValidationError

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from proj.util import JSONValue


class PdfPage(BaseModel):
    width: float
    height: float

    def as_json_dict(self) -> dict[str, JSONValue]:
        return self.model_dump()


class PdfCoordinate(BaseModel):
    """The rectangle shape used by PDF highlighting and artifact viewers."""

    model_config = ConfigDict(populate_by_name=True)

    page: int = Field(ge=1)
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    color: str | None = None
    annotation_type: str | None = Field(default=None, alias="type")
    text: str | None = None

    def as_json_dict(self) -> dict[str, JSONValue]:
        return self.model_dump(by_alias=True, exclude_none=True)


PdfPageListAdapter = TypeAdapter(list[PdfPage])
PdfCoordinateListAdapter = TypeAdapter(list[PdfCoordinate])


def normalize_pdf_pages(value: Any) -> list[dict[str, JSONValue]]:
    if value is None:
        return []

    try:
        pages = PdfPageListAdapter.validate_python(value)
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    return [page.as_json_dict() for page in pages]


def normalize_pdf_coordinates(value: Any) -> list[dict[str, JSONValue]]:
    if value is None:
        return []

    try:
        coordinates = PdfCoordinateListAdapter.validate_python(value)
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    return [coordinate.as_json_dict() for coordinate in coordinates]
