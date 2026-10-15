from unittest.mock import patch

from django.test import RequestFactory
from django.urls import reverse

import pytest
from data_fetcher import GlobalRequest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
    ReviewFactory,
    TextExtractionResultFactory,
)
from my_app.pdf.text_extraction.evidence import group_evidence_sentences
from my_app.pdf.text_extraction.tei import GrobidTeiParser
from tests.utils_for_testing import soup_from_str


def make_extraction(xml):
    return TextExtractionResultFactory(
        raw_xml=xml,
        coordinates=GrobidTeiParser(xml).get_coordinates(),
    )


PARAGRAPH_XML = """
<TEI><text>
  <p>
    <s coords="1,10,10,100,10">First.</s>
    <s coords="1,10,22,100,10">Second.</s>
    <s coords="1,10,34,100,10">Third.</s>
  </p>
  <p><s coords="1,10,46,100,10">Fourth.</s></p>
</text></TEI>
"""


def test_groups_only_consecutive_selected_sentences_in_same_paragraph():
    extraction = make_extraction(PARAGRAPH_XML)
    with GlobalRequest(request=RequestFactory().get("/")):
        assert group_evidence_sentences([3, 2, 1, 0, 1], extraction) == [
            [0, 1, 2],
            [3],
        ]
        assert group_evidence_sentences([0, 2, 3], extraction) == [
            [0],
            [2],
            [3],
        ]


@pytest.mark.parametrize(
    "coordinates",
    [
        "2,10,22,100,10",  # Page break.
        "1,210,22,100,10",  # Another column.
        "1,210,10,100,10",  # Another column at the same height.
        "1,10,100,100,10",  # Large vertical gap.
        "1,10,1,100,10",  # Reading order jumps upward.
        "1,10,22,100,10;2,10,10,100,10",  # Sentence spans pages.
        "1,10,22,100,10;1,210,10,100,10",  # Sentence spans columns.
    ],
)
def test_does_not_group_across_layout_boundaries(coordinates):
    extraction = make_extraction(
        '<TEI><text><p><s coords="1,10,10,100,10">First.</s>'
        f'<s coords="{coordinates}">Second.</s></p></text></TEI>'
    )
    assert group_evidence_sentences([0, 1], extraction) == [[0], [1]]


def test_groups_sentences_sharing_a_line_and_spanning_adjacent_lines():
    extraction = make_extraction(
        '<TEI><text><p><s coords="1,10,10,40,10">First.</s>'
        '<s coords="1,53,10,57,10;1,10,22,60,10">Second.</s>'
        '<s coords="1,73,22,37,10">Third.</s></p></text></TEI>'
    )
    assert group_evidence_sentences([0, 1, 2], extraction) == [[0, 1, 2]]


def test_repeated_sentence_text_is_ambiguous():
    extraction = make_extraction(
        '<TEI><text><p><s coords="1,10,10,100,10">Repeated.</s>'
        '<s coords="1,10,22,100,10">Next.</s></p>'
        '<p><s coords="2,10,10,100,10">Repeated.</s></p></text></TEI>'
    )
    assert group_evidence_sentences([0, 1], extraction) == [[0], [1]]


def test_missing_structure_and_invalid_indices_are_safe():
    extraction = make_extraction(PARAGRAPH_XML)
    extraction.raw_xml = ""
    assert group_evidence_sentences([0, 1, 99, -1, "0", True], extraction) == [
        [0],
        [1],
        [99],
    ]
    assert group_evidence_sentences([0, 1], None) == [[0], [1]]


@pytest.mark.parametrize("workflow", ["l2", "parameter_extraction"])
def test_detail_groups_evidence_and_parses_xml_once_per_request(
    vanilla_client, workflow
):
    extraction = make_extraction(PARAGRAPH_XML)
    review = ReviewFactory()
    row = CitationFactory(
        dataset=CitationDatasetFactory(review=review),
        document=extraction.document,
    )
    for _ in range(2):
        if workflow == "l2":
            L2ScreeningResultFactory(
                citation=row,
                question=L2ScreeningQuestionFactory(review=review),
                evidence_sentences=[0, 1, 2, 3],
            )
        else:
            ParameterExtractionResultFactory(
                citation=row,
                question=ParameterFactory(review=review),
                evidence_sentences=[0, 1, 2, 3],
            )

    if workflow == "l2":
        url = reverse("l2_citation_detail", args=[review.id, row.id])
    else:
        url = reverse(
            "parameter_extraction_citation_detail", args=[review.id, row.id]
        )

    with (
        patch_rules(can_access_review=True),
        patch(
            "my_app.pdf.text_extraction.evidence.GrobidTeiParser",
            wraps=GrobidTeiParser,
        ) as parser,
    ):
        response = vanilla_client.get(url)
        assert parser.call_count == 1
        vanilla_client.get(url)
        assert parser.call_count == 2

    assert response.status_code == 200
    soup = soup_from_str(response.content.decode())
    chips = soup.select('.evidence-chip[data-evidence-type="sentence"]')
    assert [chip.text for chip in chips] == [
        "Sentences 0–2",
        "Sentence 3",
        "Sentences 0–2",
        "Sentence 3",
    ]
    assert chips[0]["data-evidence-index"] == "0"
    assert chips[0]["data-evidence-indices"] == "0,1,2"
