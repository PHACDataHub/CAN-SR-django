from typing import Any

from pydantic import ValidationError as PydanticValidationError

from my_app.pdf.types import PdfCoordinateListAdapter


def get_sentence_list(coordinates: Any) -> list[str]:
    try:
        parsed_coordinates = PdfCoordinateListAdapter.validate_python(
            coordinates or []
        )
        annotations = [
            coordinate.text
            for coordinate in parsed_coordinates
            if coordinate.annotation_type == "s" and coordinate.text
        ]
    except PydanticValidationError:
        annotations = [
            coordinate["text"]
            for coordinate in coordinates or []
            if isinstance(coordinate, dict)
            and coordinate.get("type") == "s"
            and coordinate.get("text")
        ]

    return list(dict.fromkeys(annotations))


def get_sentences(coordinates: Any) -> str:
    full_text_arr = get_sentence_list(coordinates)
    return "\n\n".join([f"[{i}] {x}" for i, x in enumerate(full_text_arr)])
