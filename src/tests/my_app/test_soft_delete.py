from django.forms import inlineformset_factory
from django.http import QueryDict
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from proj.form_util import SoftDeleteInlineFormSet

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
    ParameterHumanAnswerFactory,
    ParameterOptionFactory,
    ReviewFactory,
)
from my_app.models import Parameter, Review, ScreeningResultStatus


def test_soft_delete_inline_formset():
    """
    The models and forms used here are just examples showcasing how to use
    soft-delete in formsets
    """
    review = ReviewFactory()
    active_parameter = ParameterFactory(
        review=review,
        name="Active parameter",
    )
    parameter_to_modify = ParameterFactory(
        review=review,
        name="Parameter to modify",
        description="Original description",
    )
    deleted_parameter = ParameterFactory(
        review=review,
        name="Soft-deleted parameter",
    )
    deleted_parameter.soft_delete()

    FormSet = inlineformset_factory(
        Review,
        Parameter,
        formset=SoftDeleteInlineFormSet,
        fields="__all__",
        can_delete=True,
        extra=1,
    )

    formset = FormSet(instance=review)
    rendered_formset = formset.as_p()

    assert "Active parameter" in rendered_formset
    assert "Parameter to modify" in rendered_formset
    assert "Soft-deleted parameter" not in rendered_formset
    assert 'type="checkbox"' in rendered_formset
    assert f'name="{formset.prefix}-0-DELETE"' in rendered_formset

    data = QueryDict(mutable=True)
    data.update(
        {
            f"{formset.prefix}-TOTAL_FORMS": "3",
            f"{formset.prefix}-INITIAL_FORMS": "2",
            f"{formset.prefix}-MIN_NUM_FORMS": "0",
            f"{formset.prefix}-MAX_NUM_FORMS": "1000",
            f"{formset.prefix}-0-id": str(active_parameter.pk),
            f"{formset.prefix}-0-review": str(review.pk),
            f"{formset.prefix}-0-name": active_parameter.name,
            f"{formset.prefix}-0-description": active_parameter.description,
            f"{formset.prefix}-0-option_type": active_parameter.option_type,
            f"{formset.prefix}-0-units_and_reporting_instructions": (
                active_parameter.units_and_reporting_instructions
            ),
            f"{formset.prefix}-0-calculation_instructions": (
                active_parameter.calculation_instructions
            ),
            f"{formset.prefix}-0-DELETE": "on",
            f"{formset.prefix}-1-id": str(parameter_to_modify.pk),
            f"{formset.prefix}-1-review": str(review.pk),
            f"{formset.prefix}-1-name": "Modified parameter",
            f"{formset.prefix}-1-description": "Modified description",
            f"{formset.prefix}-1-option_type": parameter_to_modify.option_type,
            f"{formset.prefix}-1-units_and_reporting_instructions": (
                parameter_to_modify.units_and_reporting_instructions
            ),
            f"{formset.prefix}-1-calculation_instructions": (
                parameter_to_modify.calculation_instructions
            ),
            f"{formset.prefix}-2-review": str(review.pk),
            f"{formset.prefix}-2-name": "Created parameter",
            f"{formset.prefix}-2-description": "Created description",
            f"{formset.prefix}-2-option_type": Parameter.OptionType.SELECT,
            f"{formset.prefix}-2-units_and_reporting_instructions": "kg",
            f"{formset.prefix}-2-calculation_instructions": "Add the values",
        }
    )

    bound_formset = FormSet(data=data, instance=review)
    assert bound_formset.is_valid(), bound_formset.errors

    bound_formset.save()

    active_parameter.refresh_from_db()
    assert active_parameter.deletion_time is not None
    assert not Parameter.active_objects.filter(pk=active_parameter.pk).exists()
    assert Parameter.objects.filter(pk=active_parameter.pk).exists()

    parameter_to_modify.refresh_from_db()
    assert parameter_to_modify.name == "Modified parameter"
    assert parameter_to_modify.description == "Modified description"

    created_parameter = Parameter.active_objects.get(
        review=review,
        name="Created parameter",
    )
    assert created_parameter.description == "Created description"
    assert created_parameter.option_type == Parameter.OptionType.SELECT
    assert created_parameter.units_and_reporting_instructions == "kg"
    assert created_parameter.calculation_instructions == "Add the values"


@pytest.mark.parametrize("deleted_relation", ["question", "option"])
def test_l1_post_screening_page_renders_soft_deleted_answer_relations(
    vanilla_client,
    deleted_relation,
):
    review = ReviewFactory()
    citation = CitationFactory(dataset=CitationDatasetFactory(review=review))
    question = L1ScreeningQuestionFactory(
        review=review,
        question_text="Historical L1 question",
    )
    option = L1ScreeningQuestionOptionFactory(
        question=question,
        option_text="Historical L1 option",
    )
    L1ScreeningResultFactory(
        citation=citation,
        question=question,
        selected_option=option,
        status=ScreeningResultStatus.COMPLETED,
    )
    human_answer = L1HumanAnswerFactory(
        citation=citation,
        question=question,
        selected_option=option,
    )

    soft_deleted_object = (
        question if deleted_relation == "question" else option
    )
    soft_deleted_object.soft_delete()

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("l1_citation_detail", args=[review.id, citation.id])
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert question.question_text in body
    assert option.option_text in body
    assert "AI answer" in body
    assert human_answer.user.username in body


@pytest.mark.parametrize("deleted_relation", ["question", "option"])
def test_l2_post_screening_page_renders_soft_deleted_answer_relations(
    vanilla_client,
    deleted_relation,
):
    review = ReviewFactory()
    citation = CitationFactory(dataset=CitationDatasetFactory(review=review))
    question = L2ScreeningQuestionFactory(
        review=review,
        question_text="Historical L2 question",
    )
    option = L2ScreeningQuestionOptionFactory(
        question=question,
        option_text="Historical L2 option",
    )
    L2ScreeningResultFactory(
        citation=citation,
        question=question,
        selected_option=option,
        status=ScreeningResultStatus.COMPLETED,
    )
    human_answer = L2HumanAnswerFactory(
        citation=citation,
        question=question,
        selected_option=option,
    )

    soft_deleted_object = (
        question if deleted_relation == "question" else option
    )
    soft_deleted_object.soft_delete()

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("l2_citation_detail", args=[review.id, citation.id])
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert question.question_text in body
    assert option.option_text in body
    assert "AI answer" in body
    assert human_answer.user.username in body


@pytest.mark.parametrize("deleted_relation", ["question", "option"])
def test_parameter_extraction_page_renders_soft_deleted_answer_relations(
    vanilla_client,
    deleted_relation,
):
    review = ReviewFactory()
    citation = CitationFactory(dataset=CitationDatasetFactory(review=review))
    parameter = ParameterFactory(review=review, name="Historical parameter")
    option = ParameterOptionFactory(
        parameter=parameter,
        name="Historical parameter option",
    )
    ParameterExtractionResultFactory(
        citation=citation,
        question=parameter,
        selected_option=option,
        found=True,
        value="AI extracted value",
        status=ScreeningResultStatus.COMPLETED,
    )
    human_answer = ParameterHumanAnswerFactory(
        citation=citation,
        question=parameter,
        selected_option=option,
        found=True,
        value="Human extracted value",
    )

    soft_deleted_object = (
        parameter if deleted_relation == "question" else option
    )
    soft_deleted_object.soft_delete()

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                "parameter_extraction_citation_detail",
                args=[review.id, citation.id],
            )
        )

    body = response.content.decode()
    assert response.status_code == 200
    assert parameter.name in body
    assert option.name in body
    assert "AI answer" in body
    assert human_answer.user.username in body
