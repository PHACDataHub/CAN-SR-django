from django.core.exceptions import ValidationError

from pydantic import BaseModel, Field, TypeAdapter
from pydantic import ValidationError as PydanticValidationError


class ViewerBox(BaseModel):
    """The rectangle shape expected by PDFBoundingBoxViewer."""

    page: int = Field(ge=1)
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


ViewerBoxListAdapter = TypeAdapter(list[ViewerBox])


def normalize_viewer_boxes(value) -> list[dict]:
    if value is None:
        return []

    try:
        boxes = ViewerBoxListAdapter.validate_python(value)
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    return [box.model_dump() for box in boxes]
