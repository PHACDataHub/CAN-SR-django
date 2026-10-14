from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

import pytest
import yaml
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetColumnFactory,
    CitationDatasetFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterOptionFactory,
    ReviewFactory,
)
from my_app.models import (
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    Parameter,
    ParameterOption,
    ScreeningActions,
)
from my_app.services.create_criteria_from_yaml import CreateCriteriaFromYaml


@pytest.fixture
def criteria_data():
    return {
        "citation_fields": {"l1_include": ["type"]},
        "l1": [
            {
                "question": "Primary research?",
                "answers": [
                    {
                        "label": "Yes",
                        "context": "Primary data",
                        "decision": "include",
                        "id": "ignored",
                    },
                    {
                        "label": "No",
                        "context": "Commentary",
                        "decision": "exclude",
                    },
                ],
            }
        ],
        "l2": [
            {
                "question": "English?",
                "answers": [
                    {
                        "label": "Yes",
                        "context": "English text",
                        "decision": "include",
                    },
                ],
            }
        ],
        "parameters": [
            {"name": "Delay", "description": "Time elapsed", "type": "text"}
        ],
    }


def test_import_replaces_criteria_and_cascades(criteria_data):
    dataset = CitationDatasetFactory()
    review = dataset.review
    column = CitationDatasetColumnFactory(dataset=dataset, name="type")
    old_l1 = L1ScreeningQuestionOptionFactory(question__review=review)
    old_l2 = L2ScreeningQuestionOptionFactory(question__review=review)
    old_parameter = ParameterOptionFactory(parameter__review=review)
    result = L1ScreeningResultFactory(
        question=old_l1.question,
        selected_option=old_l1,
        citation__dataset=dataset,
    )
    other = L1ScreeningQuestionOptionFactory()

    CreateCriteriaFromYaml(review, yaml.safe_dump(criteria_data)).run()

    assert not L1ScreeningQuestion.objects.filter(
        pk=old_l1.question_id
    ).exists()
    assert not L1ScreeningQuestionOption.objects.filter(pk=old_l1.pk).exists()
    assert not L2ScreeningQuestion.objects.filter(
        pk=old_l2.question_id
    ).exists()
    assert not L2ScreeningQuestionOption.objects.filter(pk=old_l2.pk).exists()
    assert not Parameter.objects.filter(pk=old_parameter.parameter_id).exists()
    assert not ParameterOption.objects.filter(pk=old_parameter.pk).exists()
    assert not L1ScreeningResult.objects.filter(pk=result.pk).exists()
    assert L1ScreeningQuestionOption.objects.filter(pk=other.pk).exists()
    assert list(dataset.screening_columns.all()) == [column]
    question = review.l1_screening_questions.get()
    assert question.question_text == "Primary research?"
    options = list(question.options.order_by("pk"))
    assert [
        (o.option_text, o.option_value, o.screening_action) for o in options
    ] == [
        ("Yes", "Primary data", ScreeningActions.ScreenIn),
        ("No", "Commentary", ScreeningActions.ScreenOut),
    ]
    mirror = review.l2_screening_questions.get(l1_question=question)
    assert mirror.question_text == question.question_text
    for option in options:
        copy = mirror.options.get(l1_option=option)
        assert (
            copy.option_text,
            copy.option_value,
            copy.screening_action,
        ) == (option.option_text, option.option_value, option.screening_action)
    assert (
        review.l2_screening_questions.get(
            l1_question__isnull=True
        ).question_text
        == "English?"
    )
    parameter = review.parameters.get()
    assert (parameter.name, parameter.description, parameter.option_type) == (
        "Delay",
        "Time elapsed",
        Parameter.OptionType.FREE_TEXT,
    )
    assert (
        parameter.units_and_reporting_instructions
        == parameter.calculation_instructions
        == ""
    )


def test_import_rolls_back_late_failure(criteria_data):
    dataset = CitationDatasetFactory()
    old_column = CitationDatasetColumnFactory(dataset=dataset)
    dataset.screening_columns.add(old_column)
    CitationDatasetColumnFactory(dataset=dataset, name="type")
    old = L1ScreeningQuestionOptionFactory(question__review=dataset.review)
    result = L1ScreeningResultFactory(
        question=old.question, selected_option=old, citation__dataset=dataset
    )
    criteria_data["parameters"][0]["type"] = "select"
    with pytest.raises(
        ValidationError, match="TODO: support more than text in yaml uploads"
    ):
        CreateCriteriaFromYaml(
            dataset.review, yaml.safe_dump(criteria_data)
        ).run()
    assert list(dataset.review.l1_screening_questions.all()) == [old.question]
    assert L1ScreeningQuestionOption.objects.filter(pk=old.pk).exists()
    assert L1ScreeningResult.objects.filter(pk=result.pk).exists()
    assert not dataset.review.l2_screening_questions.exists()
    assert list(dataset.screening_columns.all()) == [old_column]


@pytest.mark.parametrize(
    "content",
    [
        "[invalid",
        "[]",
        "{}",
        "l1: []\nl2: []\nparameters: wrong",
        "l1: []\nl2: []\nparameters: []\ncitation_fields:\n  l1_include: [missing]",
    ],
)
def test_import_rejects_invalid_document(content):
    review = ReviewFactory()
    with pytest.raises(ValidationError):
        CreateCriteriaFromYaml(review, content).run()


def test_empty_lists_are_allowed():
    old = L1ScreeningQuestionOptionFactory()
    CreateCriteriaFromYaml(
        old.question.review, "l1: []\nl2: []\nparameters: []"
    ).run()
    assert not L1ScreeningQuestion.objects.filter(pk=old.question_id).exists()


@pytest.mark.parametrize(
    "uploaded_name,column_name",
    [("type", "TYPE"), ("TYPE", "type"), ("TyPe", "tYpE")],
)
def test_screening_columns_match_case_insensitively(
    criteria_data, uploaded_name, column_name
):
    dataset = CitationDatasetFactory()
    column = CitationDatasetColumnFactory(dataset=dataset, name=column_name)
    CitationDatasetColumnFactory(name=column_name)
    criteria_data["citation_fields"]["l1_include"] = [uploaded_name]

    CreateCriteriaFromYaml(dataset.review, yaml.safe_dump(criteria_data)).run()

    assert list(dataset.screening_columns.all()) == [column]
    column.refresh_from_db()
    assert column.name == column_name


def test_import_parameter_instructions(criteria_data):
    criteria_data["citation_fields"]["l1_include"] = []
    criteria_data["parameters"][0].update(
        unit_instructions="days", calculation="subtract dates"
    )
    review = ReviewFactory()
    CreateCriteriaFromYaml(review, yaml.safe_dump(criteria_data)).run()
    parameter = review.parameters.get()
    assert parameter.units_and_reporting_instructions == "days"
    assert parameter.calculation_instructions == "subtract dates"


def test_upload_view(vanilla_user_client):
    review = ReviewFactory()
    url = reverse("criteria_upload", args=[review.pk])
    content = b"l1: []\nl2: []\nparameters: []"
    with patch_rules(can_access_review=False):
        assert vanilla_user_client.get(url).status_code == 403
        assert vanilla_user_client.post(url).status_code == 403
    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(url)
        assert response.status_code == 200
        assert b"multipart/form-data" in response.content
        assert (
            reverse("screening_criteria", args=[review.pk]).encode()
            in response.content
        )
        assert (
            url.encode()
            in vanilla_user_client.get(
                reverse("screening_criteria", args=[review.pk])
            ).content
        )
        old = L1ScreeningQuestionOptionFactory(question__review=review)
        response = vanilla_user_client.post(
            url, {"yaml_file": SimpleUploadedFile("criteria.yaml", content)}
        )
        assert response.status_code == 200
        assert "confirm_delete" in response.context["form"].errors
        assert L1ScreeningQuestion.objects.filter(pk=old.question_id).exists()
        response = vanilla_user_client.post(
            url,
            {
                "confirm_delete": "on",
                "yaml_file": SimpleUploadedFile("criteria.yaml", b"[invalid"),
            },
        )
        assert response.status_code == 200
        assert "yaml_file" in response.context["form"].errors
        assert L1ScreeningQuestion.objects.filter(pk=old.question_id).exists()
        response = vanilla_user_client.post(
            url,
            {
                "confirm_delete": "on",
                "yaml_file": SimpleUploadedFile("criteria.yml", content),
            },
        )
        assert response.status_code == 302
        assert response.url == reverse("screening_criteria", args=[review.pk])
        assert not L1ScreeningQuestion.objects.filter(
            pk=old.question_id
        ).exists()
