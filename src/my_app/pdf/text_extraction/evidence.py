from collections import defaultdict
from dataclasses import dataclass

from data_fetcher import cache_within_request
from pydantic import ValidationError

from my_app.pdf.text_extraction.tei import GrobidTeiParser
from my_app.pdf.types import PdfCoordinate, PdfCoordinateListAdapter


def boxes_are_adjacent(previous: PdfCoordinate, following: PdfCoordinate):
    """Conservatively recognize continuation on a line or the next line."""
    if previous.page != following.page:
        return False

    line_height = min(previous.height, following.height)
    if line_height <= 0:
        return False

    horizontal_overlap = min(
        previous.x + previous.width, following.x + following.width
    ) - max(previous.x, following.x)
    vertical_overlap = min(
        previous.y + previous.height, following.y + following.height
    ) - max(previous.y, following.y)

    if vertical_overlap > 0 and following.x >= previous.x:
        horizontal_gap = following.x - (previous.x + previous.width)
        if 0 <= horizontal_gap <= line_height:
            return True

    vertical_gap = following.y - (previous.y + previous.height)
    return horizontal_overlap > 0 and 0 <= vertical_gap <= line_height


@dataclass
class SentenceLocation:
    paragraph: int
    boxes: list[PdfCoordinate]


@cache_within_request
def get_sentence_locations(extraction):
    if not extraction.raw_xml:
        return {}

    try:
        coordinates = PdfCoordinateListAdapter.validate_python(
            extraction.coordinates or []
        )
    except ValidationError:
        return {}

    boxes_by_text = defaultdict(list)
    for coordinate in coordinates:
        if coordinate.annotation_type == "s" and coordinate.text:
            boxes_by_text[coordinate.text].append(coordinate)

    soup = GrobidTeiParser(extraction.raw_xml).soup
    paragraphs = {
        id(paragraph): i for i, paragraph in enumerate(soup.find_all("p"))
    }
    sentences_by_text = defaultdict(list)
    for sentence in soup.find_all("s", coords=True):
        sentences_by_text[sentence.text].append(sentence)

    locations = {}
    # Keep the same text-deduplicated order as the AI's sentence indices.
    for index, (text, boxes) in enumerate(boxes_by_text.items()):
        sentences = sentences_by_text[text]
        if len(sentences) != 1:
            continue
        paragraph = sentences[0].find_parent("p")
        if paragraph is None:
            continue
        if any(
            not boxes_are_adjacent(previous, following)
            for previous, following in zip(boxes, boxes[1:])
        ):
            continue
        locations[index] = SentenceLocation(paragraphs[id(paragraph)], boxes)
    return locations


def group_evidence_sentences(indices, extraction):
    if not indices:
        return []

    locations = {}
    if extraction is not None:
        locations = get_sentence_locations(extraction)

    valid_indices = sorted(
        {index for index in indices if type(index) is int and index >= 0}
    )
    groups = []
    for index in valid_indices:
        current = locations.get(index)
        previous = None
        if groups:
            previous = locations.get(groups[-1][-1])
        if (
            previous is not None
            and current is not None
            and index == groups[-1][-1] + 1
            and previous.paragraph == current.paragraph
            and boxes_are_adjacent(previous.boxes[-1], current.boxes[0])
        ):
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups
