from django.urls import reverse
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    SystematicReviewFactory,
    SystematicReviewUserLinkFactory,
)
from my_app.models import (
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    ParameterQuestion,
    ParameterQuestionOption,
    SystematicReview,
)
from my_app.views.screening_criteria import (
    ChildEditor,
    L1FormsetAdapter,
    L2FormsetAdapter,
    ParameterFormsetAdapter,
)
from tests.utils_for_testing import (
    add_formset_prefix,
    add_prefix,
    get_base_formset_params,
)


def test_editor_helper_class_new_question():
    review = SystematicReviewFactory()
    unsaved_obj = L1ScreeningQuestion(review=review)
    prefix = "test-prefix"
    fs_prefix = "test-prefix-options"

    data = {
        **add_prefix(
            fs_prefix,
            {"TOTAL_FORMS": 2, "INITIAL_FORMS": 0},
        ),
        **add_prefix(
            prefix,
            {
                "question_text": "Is this a test question?",
            },
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
        prefix=prefix,
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

    prefix = "test-prefix"
    fs_prefix = "test-prefix-options"

    data = {
        **add_prefix(
            fs_prefix,
            {"TOTAL_FORMS": 2, "INITIAL_FORMS": 1},
        ),
        **add_prefix(
            prefix,
            {"question_text": "Is this a modified test question?"},
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
        child=question_obj, prefix=prefix, data=data, adapter=L1FormsetAdapter
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
    prefix = "test-prefix"
    fs_prefix = "test-prefix-options"

    data = {
        **add_prefix(
            fs_prefix,
            {"TOTAL_FORMS": 1, "INITIAL_FORMS": 0},
        ),
        **add_prefix(
            prefix,
            {
                "question_text": "Test parameter",
            },
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
        prefix=prefix,
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
