import pytest

from my_app.models import Document, DocumentMetadata
from my_app.pdf.text_extraction.tei import GrobidTeiParser
from my_app.pdf.types import PdfCoordinate, PdfPage

XML = """
<TEI>
  <text>
    <p coords="1,10,20,30,40;2,15,25,35,45;">Paragraph</p>
    <head coords="2,50,60,70,80">Heading</head>
  </text>
  <surface ulx="0" uly="0" lrx="612" lry="792" />
  <surface ulx="10" uly="20" lrx="210" lry="320" />
</TEI>
"""

# richer example for sake of testing sentence extraction
SENTENCE_XML = """
<TEI>
  <text>
    <p coords="1,10,20,30,40;1,40,50,60,70;">
      <s coords="1,10,20,30,40;1,40,50,60,70;">First sentence.</s>
      <s coords="1,80,90,100,110;">Second sentence.</s>
    </p>
    <head coords="2,50,60,70,80">Heading</head>
  </text>
  <surface ulx="0" uly="0" lrx="612" lry="792" />
  <surface ulx="10" uly="20" lrx="210" lry="320" />
</TEI>
"""


def test_get_pages_returns_width_and_height_for_each_surface():
    processor = GrobidTeiParser(XML)

    assert processor.get_pages() == [
        {"width": 612.0, "height": 792.0},
        {"width": 200.0, "height": 300.0},
    ]


def test_get_page_models_returns_typed_page_dimensions():
    processor = GrobidTeiParser(XML)

    pages = processor.get_page_models()

    assert pages == [
        PdfPage(width=612.0, height=792.0),
        PdfPage(width=200.0, height=300.0),
    ]


def test_get_coordinates_returns_one_entry_per_box_with_metadata():
    processor = GrobidTeiParser(XML)

    assert processor.get_coordinates() == [
        {
            "page": 1,
            "x": 10.0,
            "y": 20.0,
            "width": 30.0,
            "height": 40.0,
            "color": "rgba(139, 0, 0, 0.4)",
            "type": "p",
            "text": "Paragraph",
        },
        {
            "page": 2,
            "x": 15.0,
            "y": 25.0,
            "width": 35.0,
            "height": 45.0,
            "color": "rgba(139, 0, 0, 0.4)",
            "type": "p",
            "text": "Paragraph",
        },
        {
            "page": 2,
            "x": 50.0,
            "y": 60.0,
            "width": 70.0,
            "height": 80.0,
            "color": "rgba(139, 139, 0, 1)",
            "type": "head",
            "text": "Heading",
        },
    ]


def test_get_coordinate_models_returns_typed_coordinates():
    processor = GrobidTeiParser(XML)

    coordinates = processor.get_coordinate_models()

    assert coordinates[0] == PdfCoordinate(
        page=1,
        x=10.0,
        y=20.0,
        width=30.0,
        height=40.0,
        color="rgba(139, 0, 0, 0.4)",
        annotation_type="p",
        text="Paragraph",
    )


def test_box_to_coordinate_rejects_malformed_coordinate_box():
    with pytest.raises(
        ValueError,
        match="Expected a Grobid coordinate box with 5 values",
    ):
        GrobidTeiParser._box_to_coordinate(["1", "10", "20"])


def test_get_sentences_returns_unique_sentence_text_in_order():
    document = Document(
        id=1,
        file="documents/example.pdf",
    )
    metadata = DocumentMetadata(
        document=document,
        coordinates=GrobidTeiParser(SENTENCE_XML).get_coordinates(),
    )

    assert metadata.get_sentences() == (
        "[0] First sentence.\n\n[1] Second sentence."
    )
