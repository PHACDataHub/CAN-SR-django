from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    SystematicReviewFactory,
    SystematicReviewUserLinkFactory,
)
from my_app.models import (
    CitationDataset,
    CitationDatasetColumn,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    ParameterQuestion,
    ParameterQuestionOption,
)
from my_app.views.screening_criteria import (
    ChildEditor,
    L1FormsetAdapter,
    L2FormsetAdapter,
    ParameterFormsetAdapter,
)
from tests.utils_for_testing import add_formset_prefix, add_prefix


def test_editor_helper_class_new_question():
    review = SystematicReviewFactory()
    unsaved_obj = L1ScreeningQuestion(review=review)
    fs_prefix = "options"

    data = {
        "question_text": "Is this a test question?",
        **add_prefix(
            fs_prefix,
            {"TOTAL_FORMS": 2, "INITIAL_FORMS": 0},
        ),
        **add_formset_prefix(
            fs_prefix,
            0,
            {"option_text": "Option 1", "option_value": "The first option"},
        ),
        **add_formset_prefix(
            fs_prefix,
            1,
            {"option_text": "Option 2", "option_value": "The second option"},
        ),
    }

    editor = ChildEditor(
        child=unsaved_obj,
        data=data,
        adapter=L1FormsetAdapter,
    )
    editor.save()

    assert L1ScreeningQuestion.objects.count() == 1
    question = L1ScreeningQuestion.objects.first()

    assert question.review == review
    assert question.question_text == "Is this a test question?"

    assert question.options.count() == 2
    option1 = question.options.first()
    option2 = question.options.last()
    assert option1.option_text == "Option 1"
    assert option1.option_value == "The first option"
    assert option2.option_text == "Option 2"
    assert option2.option_value == "The second option"


def test_editor_helper_class_modify_question():
    review = SystematicReviewFactory()
    question_obj = L1ScreeningQuestion.objects.create(review=review)
    question_option1 = L1ScreeningQuestionOption.objects.create(
        question=question_obj, option_text="Option 1", option_value="1"
    )

    fs_prefix = "options"

    data = {
        "question_text": "Is this a modified test question?",
        **add_prefix(
            fs_prefix,
            {"TOTAL_FORMS": 2, "INITIAL_FORMS": 1},
        ),
        **add_formset_prefix(
            fs_prefix,
            0,
            {
                "id": question_option1.id,
                "option_text": "Modified Option 1",
                "option_value": "Modified value 1",
            },
        ),
        **add_formset_prefix(
            fs_prefix,
            1,
            {"option_text": "Option 2", "option_value": "The second option"},
        ),
    }

    editor = ChildEditor(
        child=question_obj,
        data=data,
        adapter=L1FormsetAdapter,
    )
    editor.save()

    assert L1ScreeningQuestion.objects.count() == 1
    question = L1ScreeningQuestion.objects.first()
    assert question.review == review
    assert question.question_text == "Is this a modified test question?"
    assert question.pk == question_obj.pk

    assert question.options.count() == 2
    option1, option2, *_ = question.options.order_by("id").all()
    assert option1.pk == question_option1.pk
    assert option1.option_text == "Modified Option 1"
    assert option1.option_value == "Modified value 1"

    assert option2.option_text == "Option 2"
    assert option2.option_value == "The second option"


def test_editor_helper_new_parameter():
    review = SystematicReviewFactory()
    unsaved_obj = ParameterQuestion(review=review)
    fs_prefix = "options"

    data = {
        "question_text": "Test parameter",
        **add_prefix(
            fs_prefix,
            {"TOTAL_FORMS": 1, "INITIAL_FORMS": 0},
        ),
        **add_formset_prefix(
            fs_prefix,
            0,
            {
                "param_name": "Option 1",
                "param_description": "The first option",
            },
        ),
    }

    editor = ChildEditor(
        child=unsaved_obj,
        data=data,
        adapter=ParameterFormsetAdapter,
    )
    editor.save()

    assert ParameterQuestion.objects.count() == 1
    param = ParameterQuestion.objects.first()

    assert param.review == review
    assert param.question_text == "Test parameter"

    assert param.options.count() == 1
    option1 = param.options.first()
    assert option1.param_name == "Option 1"
    assert option1.param_description == "The first option"


def test_editor_new_invalid_data():
    review = SystematicReviewFactory()
    unsaved_obj = L1ScreeningQuestion(review=review)
    fs_prefix = "options"

    data = {
        "question_text": "Is this a test question?",
        **add_prefix(
            fs_prefix,
            {"TOTAL_FORMS": 1, "INITIAL_FORMS": 0},
        ),
        **add_formset_prefix(
            fs_prefix,
            0,
            {
                # missing option_text (required)
                "option_text": "",
                "option_value": "The first option",
            },
        ),
    }

    editor = ChildEditor(
        child=unsaved_obj,
        data=data,
        adapter=L1FormsetAdapter,
    )
    assert not editor.is_valid()
    assert editor.child_form.is_valid()
    assert editor.option_formset.is_valid() is False


def _linked_review(title, user):
    review = SystematicReviewFactory(title=title)
    SystematicReviewUserLinkFactory(user=user, systematic_review=review)
    return review


def _create_dataset(review, column_names):
    dataset = CitationDataset.objects.create(systematic_review=review)
    columns = [
        CitationDatasetColumn.objects.create(dataset=dataset, name=name)
        for name in column_names
    ]
    return dataset, columns


def _create_review_with_dataset(vanilla_user, column_names):
    review = _linked_review("Dataset review", vanilla_user)
    dataset, columns = _create_dataset(review, column_names)
    return review, dataset, columns


def _get_page_body(vanilla_user_client, review):
    url = reverse("screening_criteria", args=[review.id])
    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.get(url)

    assert response.status_code == 200
    return response.content.decode()


def _assert_modal_smoke(response, form_id, *expected_texts):
    assert response.status_code == 200

    body = response.content.decode()
    assert f'id="{form_id}"' in body
    assert "Cancel" in body
    assert "Save" in body
    for text in expected_texts:
        assert text in body


def _make_l1_child(review, question_text="Existing L1 question"):
    question = L1ScreeningQuestion.objects.create(
        review=review,
        question_text=question_text,
    )
    option = L1ScreeningQuestionOption.objects.create(
        question=question,
        option_text="Yes",
        option_value="Proceed",
    )
    return question, option


def _make_l2_child(review, question_text="Existing L2 question"):
    question = L2ScreeningQuestion.objects.create(
        review=review,
        question_text=question_text,
    )
    option = L2ScreeningQuestionOption.objects.create(
        question=question,
        option_text="Maybe",
        option_value="Needs review",
    )
    return question, option


def _make_parameter_child(review, question_text="Existing parameter question"):
    question = ParameterQuestion.objects.create(
        review=review,
        question_text=question_text,
    )
    option = ParameterQuestionOption.objects.create(
        question=question,
        param_name="Age",
        param_description="Adults only",
    )
    return question, option


def test_screening_criteria_page_renders_empty_sections(
    vanilla_user_client, vanilla_user
):
    review = _linked_review("Empty screening review", vanilla_user)

    body = _get_page_body(vanilla_user_client, review)

    assert "Screening columns" in body
    assert "No citation dataset yet." in body
    assert 'id="edit-screening-columns-button"' not in body


def test_screening_criteria_page_renders_existing_questions(
    vanilla_user_client, vanilla_user
):
    review = _linked_review("Populated screening review", vanilla_user)
    l1_question, _ = _make_l1_child(review, "L1 question")
    l2_question, _ = _make_l2_child(review, "L2 question")
    parameter_question, _ = _make_parameter_child(review, "Parameter question")

    body = _get_page_body(vanilla_user_client, review)

    assert "L1 question" in body
    assert "Yes" in body
    assert "Proceed" in body
    assert (
        f'id="edit-l1formsetadapter-section-{l1_question.pk}-button"' in body
    )

    assert "L2 question" in body
    assert "Maybe" in body
    assert "Needs review" in body
    assert (
        f'id="edit-l2formsetadapter-section-{l2_question.pk}-button"' in body
    )

    assert "Parameter question" in body
    assert "Age" in body
    assert "Adults only" in body
    assert (
        f'id="edit-parameterformsetadapter-section-{parameter_question.pk}-button"'
        in body
    )


def test_screening_criteria_page_renders_screening_columns(
    vanilla_user_client, vanilla_user
):
    review, dataset, columns = _create_review_with_dataset(
        vanilla_user,
        ["year", "month", "day"],
    )
    dataset.screening_columns.set([columns[0], columns[2]])

    body = _get_page_body(vanilla_user_client, review)

    assert "Screening columns" in body
    assert "year" in body
    assert "day" in body
    assert "month" not in body
    assert 'id="edit-screening-columns-button"' in body


def test_edit_screening_columns_modal_gets_current_values(
    vanilla_user_client, vanilla_user
):
    review, dataset, columns = _create_review_with_dataset(
        vanilla_user,
        ["year", "month", "day"],
    )
    dataset.screening_columns.set([columns[0], columns[2]])
    url = reverse("edit_screening_columns", args=[review.id])

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.get(url)

    _assert_modal_smoke(
        response,
        "screening-columns-form",
        "Edit screening columns",
        "year",
        "month",
        "day",
    )
    body = response.content.decode()
    assert f'value="{columns[0].pk}"' in body
    assert f'value="{columns[1].pk}"' in body
    assert f'value="{columns[2].pk}"' in body
    assert (
        f'value="{columns[0].pk}" id="id_screening_columns_0" checked' in body
    )
    assert (
        f'value="{columns[2].pk}" id="id_screening_columns_2" checked' in body
    )


def test_edit_screening_columns_modal_saves_and_returns_page(
    vanilla_user_client, vanilla_user
):
    review, dataset, columns = _create_review_with_dataset(
        vanilla_user,
        ["year", "month", "day"],
    )
    dataset.screening_columns.set([columns[0]])
    url = reverse("edit_screening_columns", args=[review.id])

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.post(
            url,
            {
                "screening_columns": [
                    str(columns[1].pk),
                    str(columns[2].pk),
                ]
            },
        )

    assert response.status_code == 200
    assert response["HX-Trigger-After-Settle"] == "modal-close"
    assert response["Hx-Reswap"] == "none"

    dataset.refresh_from_db()
    assert list(
        dataset.screening_columns.order_by("id").values_list("name", flat=True)
    ) == ["month", "day"]

    body = response.content.decode()
    assert 'id="screening-columns-section"' in body
    assert 'hx-swap-oob="true"' in body
    assert "month" in body
    assert "day" in body
    assert "year" not in body


def test_edit_screening_columns_modal_rejects_invalid_choice(
    vanilla_user_client, vanilla_user
):
    review, dataset, columns = _create_review_with_dataset(
        vanilla_user,
        ["year", "month", "day"],
    )
    dataset.screening_columns.set([columns[0]])
    url = reverse("edit_screening_columns", args=[review.id])

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.post(
            url,
            {"screening_columns": ["999999"]},
        )

    assert response.status_code == 200
    assert response["HX-Refocus"] == "#screening-columns-form"
    dataset.refresh_from_db()
    assert list(
        dataset.screening_columns.order_by("id").values_list("name", flat=True)
    ) == ["year"]

    body = response.content.decode()
    assert "Select a valid choice" in body
    assert "Edit screening columns" in body


def test_screening_criteria_page_shows_message_without_dataset(
    vanilla_user_client, vanilla_user
):
    review = _linked_review("No dataset review", vanilla_user)

    body = _get_page_body(vanilla_user_client, review)

    assert "No citation dataset yet." in body
    assert 'id="edit-screening-columns-button"' not in body


def test_add_l1_question_modal_saves_valid_data(
    vanilla_user_client, vanilla_user
):
    review = _linked_review("Create L1 review", vanilla_user)
    url = reverse("add_l1_question", args=[review.pk])
    data = {
        "question_text": "Is this a test question?",
        **add_prefix("options", {"TOTAL_FORMS": 2, "INITIAL_FORMS": 0}),
        **add_formset_prefix(
            "options",
            0,
            {"option_text": "Option 1", "option_value": "The first option"},
        ),
        **add_formset_prefix(
            "options",
            1,
            {"option_text": "Option 2", "option_value": "The second option"},
        ),
    }

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.post(url, data)

    assert response.status_code == 200
    assert response["HX-Trigger-After-Settle"] == "modal-close"

    question = L1ScreeningQuestion.objects.get(review=review)
    assert question.question_text == "Is this a test question?"
    assert question.options.count() == 2
    assert question.options.filter(option_text="Option 1").exists()
    assert question.options.filter(option_text="Option 2").exists()

    body = response.content.decode()
    assert "Is this a test question?" in body
    assert "Option 1" in body
    assert "Option 2" in body


def test_add_l1_question_modal_shows_errors_for_invalid_data(
    vanilla_user_client, vanilla_user
):
    review = _linked_review("Invalid L1 review", vanilla_user)
    url = reverse("add_l1_question", args=[review.pk])
    data = {
        "question_text": "Is this a test question?",
        **add_prefix("options", {"TOTAL_FORMS": 1, "INITIAL_FORMS": 0}),
        **add_formset_prefix(
            "options",
            0,
            {"option_text": "", "option_value": "The first option"},
        ),
    }

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.post(url, data)

    assert response.status_code == 200
    assert response["HX-Refocus"] == "#L1FormsetAdapter-error-summary"
    assert L1ScreeningQuestion.objects.filter(review=review).count() == 0

    body = response.content.decode()
    assert 'id="L1FormsetAdapter"' in body
    assert "form-error-summary" in body
    assert "This field is required." in body


def _add_l2_question_url(review):
    return reverse("add_l2_question", args=[review.pk])


def _add_parameter_question_url(review):
    return reverse("add_parameter_question", args=[review.pk])


def _edit_l1_question_url(review):
    question, _ = _make_l1_child(review, "Editable L1 question")
    return reverse("edit_l1_question", args=[review.pk, question.pk])


def _edit_l2_question_url(review):
    question, _ = _make_l2_child(review, "Editable L2 question")
    return reverse("edit_l2_question", args=[review.pk, question.pk])


def _edit_parameter_question_url(review):
    question, _ = _make_parameter_child(review, "Editable parameter question")
    return reverse("edit_parameter_question", args=[review.pk, question.pk])


@pytest.mark.parametrize(
    "url_builder, form_id, expected_texts",
    [
        (
            _add_l2_question_url,
            "L2FormsetAdapter",
            ("Question text", "Add option", "Save"),
        ),
        (
            _add_parameter_question_url,
            "ParameterFormsetAdapter",
            ("Parameter", "Add option", "Save"),
        ),
        (
            _edit_l1_question_url,
            "L1FormsetAdapter",
            ("Editable L1 question", "Yes", "Proceed"),
        ),
        (
            _edit_l2_question_url,
            "L2FormsetAdapter",
            ("Editable L2 question", "Maybe", "Needs review"),
        ),
        (
            _edit_parameter_question_url,
            "ParameterFormsetAdapter",
            ("Editable parameter question", "Age", "Adults only"),
        ),
    ],
)
def test_other_screening_criteria_modals_render(
    vanilla_user_client,
    vanilla_user,
    url_builder,
    form_id,
    expected_texts,
):
    review = _linked_review(f"{form_id} review", vanilla_user)
    url = url_builder(review)

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.get(url)

    _assert_modal_smoke(response, form_id, *expected_texts)
