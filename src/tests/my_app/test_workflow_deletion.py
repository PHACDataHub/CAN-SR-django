from contextlib import contextmanager
from io import BytesIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    FigureExtractionResultFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterHumanAnswerFactory,
    PdfFromDOIRequestFactory,
    ReviewFactory,
    TextExtractionResultFactory,
)
from my_app.models import (
    Document,
    DocumentFigure,
    DocumentTable,
    PdfFromDOIRequest,
    ScreeningResultStatus,
)
from my_app.services.doi_pdf_service import DoiPdfService, QueueDoiPdfService

pytestmark = pytest.mark.view


@pytest.mark.parametrize(
    "stage,answer_factory,result_factory",
    [
        ("l1", L1HumanAnswerFactory, L1ScreeningResultFactory),
        ("l2", L2HumanAnswerFactory, L2ScreeningResultFactory),
    ],
)
def test_delete_question_keeps_history(
    vanilla_client, stage, answer_factory, result_factory
):
    answer = answer_factory()
    question = answer.question
    result = result_factory(citation=answer.citation, question=question)
    url = reverse(
        f"delete_{stage}_question", args=[question.review_id, question.pk]
    )
    other_review_url = reverse(
        f"delete_{stage}_question", args=[ReviewFactory().pk, question.pk]
    )
    if stage == "l1":
        mirror = question.sync_to_l2()
        mirror_answer = L2HumanAnswerFactory(
            citation=answer.citation, question=mirror
        )
        mirror_url = reverse(
            "delete_l2_question", args=[question.review_id, mirror.pk]
        )

    with patch_rules(can_access_review=False):
        assert vanilla_client.post(url).status_code == 403
    with patch_rules(can_access_review=True):
        assert vanilla_client.post(other_review_url).status_code == 404
        confirmation = vanilla_client.get(url)
        assert confirmation.status_code == 200
        assert question.__class__.active_objects.filter(
            pk=question.pk
        ).exists()
        if stage == "l1":
            assert b"its L2 copy" in confirmation.content
            assert vanilla_client.post(mirror_url).status_code == 404
        response = vanilla_client.post(url)

    assert response.status_code == 200
    assert question.question_text.encode() not in response.content
    question.refresh_from_db()
    assert question.is_deleted
    answer.refresh_from_db()
    result.refresh_from_db()
    if stage == "l1":
        mirror.refresh_from_db()
        assert mirror.is_deleted
        mirror_answer.refresh_from_db()


def test_delete_pdf_clears_only_pdf_work_and_allows_new_download(
    vanilla_client, settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = tmp_path
    settings.UNPAYWALL_EMAIL = "contact@example.org"
    document = DocumentFactory()
    citation = CitationFactory(document=document, doi="10.1234/example")
    request = PdfFromDOIRequestFactory(
        citation=citation, status=PdfFromDOIRequest.Status.FULFILLED
    )
    args = [citation.dataset.review_id, citation.pk]
    delete_url = reverse("citation_delete_pdf", args=[*args, document.pk])
    download_url = reverse("citation_download_pdf_from_doi", args=args)

    text = TextExtractionResultFactory(document=document, status="completed")
    figures = FigureExtractionResultFactory(
        document=document, status="completed"
    )
    figure = DocumentFigure.objects.create(
        document=document,
        index=1,
        file=ContentFile(b"figure", name="figure.png"),
    )
    table = DocumentTable.objects.create(
        document=document, index=1, table_markdown="test"
    )
    l1, l2, parameter = [
        factory(citation=citation, status=ScreeningResultStatus.COMPLETED)
        for factory in (
            L1ScreeningResultFactory,
            L2ScreeningResultFactory,
            ParameterExtractionResultFactory,
        )
    ]
    answers = [
        factory(citation=citation, question=result.question)
        for factory, result in (
            (L1HumanAnswerFactory, l1),
            (L2HumanAnswerFactory, l2),
            (ParameterHumanAnswerFactory, parameter),
        )
    ]

    with patch_rules(can_access_review=False):
        assert vanilla_client.post(delete_url).status_code == 403
    with patch_rules(can_access_review=True):
        other_review_url = reverse(
            "citation_delete_pdf",
            args=[ReviewFactory().pk, citation.pk, document.pk],
        )
        assert vanilla_client.post(other_review_url).status_code == 404
        assert vanilla_client.get(delete_url).status_code == 200
        with django_capture_on_commit_callbacks(execute=True):
            response = vanilla_client.post(delete_url)
            assert response["HX-Trigger"] == "citations-update"
            assert document.file.storage.exists(document.file.name)
            assert figure.file.storage.exists(figure.file.name)

        assert vanilla_client.get(delete_url).status_code == 404
        assert (
            vanilla_client.get(
                reverse("citation_download_pdf_document", args=args)
            ).status_code
            == 404
        )
        with (
            patch.object(QueueDoiPdfService, "enqueue") as enqueue,
            django_capture_on_commit_callbacks(execute=True),
        ):
            assert vanilla_client.post(download_url).status_code == 200

    citation.refresh_from_db()
    assert citation.document_id is None
    assert citation.doi == "10.1234/example"
    l1.refresh_from_db()
    for answer in answers:
        answer.refresh_from_db()
    for deleted in (document, text, figures, figure, table, l2, parameter):
        assert not deleted.__class__.objects.filter(pk=deleted.pk).exists()
    assert not document.file.storage.exists(document.file.name)
    assert not figure.file.storage.exists(figure.file.name)
    previous_run_id = request.run_id
    request.refresh_from_db()
    assert request.status == PdfFromDOIRequest.Status.PENDING
    assert request.run_id != previous_run_id
    enqueue.assert_called_once_with(request.pk, str(request.run_id))

    @contextmanager
    def download(url):
        yield BytesIO(b"%PDF-1.4\nreplacement")

    with (
        patch(
            "my_app.services.doi_pdf_service.iter_doi_pdf_urls",
            return_value=["https://example.org/article.pdf"],
        ),
        patch("my_app.services.doi_pdf_service.download_pdf", download),
    ):
        outcome = DoiPdfService(citation).perform()

    assert outcome.status == PdfFromDOIRequest.Status.FULFILLED
    citation.refresh_from_db()
    assert citation.document.file.read() == b"%PDF-1.4\nreplacement"
    l1.refresh_from_db()
    for answer in answers:
        answer.refresh_from_db()


@pytest.mark.parametrize(
    "blocker,expected",
    [
        ("shared", b"This PDF is shared"),
        ("processing", b"Wait for processing to finish"),
        ("download", b"Wait for the PDF download to finish"),
        ("changed", b"The attached PDF has changed"),
    ],
)
def test_delete_pdf_rejects_unsafe_removal(
    vanilla_client, settings, tmp_path, blocker, expected
):
    settings.MEDIA_ROOT = tmp_path
    document = DocumentFactory()
    citation = CitationFactory(document=document)
    url = reverse(
        "citation_delete_pdf",
        args=[citation.dataset.review_id, citation.pk, document.pk],
    )
    current_document = document
    if blocker == "shared":
        other_citation = CitationFactory(document=document)
    elif blocker == "processing":
        TextExtractionResultFactory(document=document)
    elif blocker == "download":
        PdfFromDOIRequestFactory(citation=citation)
    elif blocker == "changed":
        current_document = DocumentFactory()
        citation.document = current_document
        citation.save(update_fields=["document"])

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(url)

    assert expected in response.content
    citation.refresh_from_db()
    assert citation.document_id == current_document.pk
    assert Document.objects.filter(pk=document.pk).exists()
    assert document.file.storage.exists(document.file.name)
    if blocker == "shared":
        other_citation.refresh_from_db()
        assert other_citation.document_id == document.pk
