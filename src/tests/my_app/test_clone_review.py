from unittest.mock import patch

from django.urls import reverse

from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetColumnFactory,
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterOptionFactory,
    Phase2CitationWorkflowRequestFactory,
    ReviewFactory,
    ReviewUserLinkFactory,
    TextExtractionResultFactory,
)
from my_app.models import (
    Document,
    DocumentFigure,
    L1HumanAnswer,
    L1ScreeningResult,
    Phase2CitationWorkflowRequest,
    Review,
    TextExtractionResult,
)
from my_app.services.doi_pdf_service import delete_unreferenced_document_file


def test_clone_review_requires_access_and_confirmation(vanilla_client):
    review = ReviewFactory()
    url = reverse("clone_review", args=[review.pk])

    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
        assert vanilla_client.post(url, {"confirm": True}).status_code == 403

    with patch_rules(can_access_review=True):
        edit = vanilla_client.get(reverse("edit_review", args=[review.pk]))
        assert f'hx-get="{url}"' in edit.content.decode()
        assert (
            'id="clone-review-modal"'
            in vanilla_client.get(url).content.decode()
        )
        response = vanilla_client.post(url)
        assert "This field is required." in response.content.decode()

    assert Review.objects.count() == 1


def test_clone_review_copies_inputs_and_redirects(
    vanilla_client, vanilla_user
):
    source = ReviewFactory(disable_filtering=True, confidence=0.75)
    ReviewUserLinkFactory(review=source, user=vanilla_user)
    ReviewUserLinkFactory(review=source)
    dataset = CitationDatasetFactory(review=source)
    selected = CitationDatasetColumnFactory(dataset=dataset, name="Authors")
    CitationDatasetColumnFactory(dataset=dataset, name="Year")
    dataset.screening_columns.add(selected)
    document = DocumentFactory(file="documents/source.pdf")
    citation = CitationFactory(
        dataset=dataset,
        document=document,
        doi="10.1234/example",
        data={"Authors": "Smith", "Year": "2024"},
    )
    CitationFactory(dataset=dataset, document=document)
    CitationFactory(dataset=dataset)

    l1 = L1ScreeningQuestionOptionFactory(question__review=source)
    l2 = L2ScreeningQuestionOptionFactory(question__review=source)
    option = ParameterOptionFactory(parameter__review=source)
    L1HumanAnswerFactory(
        citation=citation, question=l1.question, selected_option=l1
    )
    L1ScreeningResultFactory(citation=citation, question=l1.question)
    workflow = Phase2CitationWorkflowRequestFactory(citation=citation)
    TextExtractionResultFactory(document=document, workflow_request=workflow)
    DocumentFigure.objects.create(document=document, index=1)

    url = reverse("clone_review", args=[source.pk])
    with patch.object(document.file.storage, "save") as save_file:
        response = vanilla_client.post(
            url, {"confirm": True}, HTTP_HX_REQUEST="true"
        )
    save_file.assert_not_called()

    clone = Review.objects.exclude(pk=source.pk).get()
    assert response.status_code == 200
    assert response["HX-Redirect"] == reverse("review_detail", args=[clone.pk])
    assert vanilla_client.get(response["HX-Redirect"]).status_code == 200
    assert clone.title == source.title + " (copy)"
    assert clone.description == source.description
    assert clone.disable_filtering and clone.confidence == 0.75
    assert list(clone.users.all()) == [vanilla_user]

    copied_l1 = clone.l1_screening_questions.get()
    copied_l2 = clone.l2_screening_questions.get()
    copied_parameter = clone.parameters.get()
    assert copied_l1.pk != l1.question_id
    assert copied_l1.question_text == l1.question.question_text
    assert copied_l1.options.get().option_value == l1.option_value
    assert copied_l2.options.get().option_value == l2.option_value
    assert copied_parameter.options.get().context == option.context

    copied_dataset = clone.citation_dataset
    assert set(copied_dataset.columns.values_list("name", flat=True)) == {
        "Authors",
        "Year",
    }
    copied_column = copied_dataset.screening_columns.get()
    assert copied_column.name == selected.name
    assert copied_column.pk != selected.pk
    assert copied_column.dataset_id == copied_dataset.pk
    copied, same_document, no_document = copied_dataset.rows.all()
    assert copied.pk != citation.pk
    assert (
        copied.title,
        copied.abstract,
        copied.doi,
        copied.data,
        copied.order,
    ) == (
        citation.title,
        citation.abstract,
        citation.doi,
        citation.data,
        citation.order,
    )
    assert copied.document_id != document.pk
    assert copied.document.file.name == document.file.name
    assert same_document.document_id == copied.document_id
    assert no_document.document_id is None
    assert not copied.document.documentfigures.exists()
    assert not TextExtractionResult.objects.filter(
        document=copied.document
    ).exists()
    assert not Phase2CitationWorkflowRequest.objects.filter(
        citation=copied
    ).exists()
    assert not L1HumanAnswer.objects.filter(citation=copied).exists()
    assert not L1ScreeningResult.objects.filter(citation=copied).exists()

    with patch.object(document.file.storage, "delete") as delete_file:
        document.delete()
        delete_unreferenced_document_file(
            document.file.storage, document.file.name
        )
        delete_file.assert_not_called()
        Document.objects.get(pk=copied.document_id).delete()
        delete_unreferenced_document_file(
            document.file.storage, document.file.name
        )
        delete_file.assert_called_once_with(document.file.name)


def test_clone_review_without_dataset_uses_standard_redirect(
    vanilla_client, vanilla_user
):
    source = ReviewFactory(title="A" * 255, is_deleted=True)
    ReviewUserLinkFactory(review=source, user=vanilla_user)
    response = vanilla_client.post(
        reverse("clone_review", args=[source.pk]), {"confirm": True}
    )

    clone = Review.objects.exclude(pk=source.pk).get()
    assert response.status_code == 302
    assert response.url == reverse("review_detail", args=[clone.pk])
    assert not clone.is_deleted
    assert len(clone.title) == 255
    assert clone.title.endswith(" (copy)")
    assert not hasattr(clone, "citation_dataset")
