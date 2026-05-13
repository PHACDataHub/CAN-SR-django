from my_app.model_factories import SystematicReviewFactory
from my_app.models import (
    CitationDataset,
    CitationDatasetColumn,
    CitationDatasetRow,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    SystematicReview,
)
from my_app.prompts.screening_prompt import L1ScreeningPromptBuilder


def test_screening_prompt_builder():
    sr = SystematicReviewFactory()
    dataset = CitationDataset.objects.create(systematic_review=sr)
    col1 = CitationDatasetColumn.objects.create(
        dataset=dataset, name="custom_col1"
    )
    col2 = CitationDatasetColumn.objects.create(
        dataset=dataset, name="custom_col2"
    )

    dataset.screening_columns.set([col1])

    row = CitationDatasetRow.objects.create(
        dataset=dataset,
        title="Test Title",
        abstract="Test Abstract",
        data={
            "custom_col1": "Custom Value 1",
            "custom_col2": "Custom Value 2",
        },
        order=1,
    )

    question = L1ScreeningQuestion.objects.create(
        review=sr, question_text="Is this relevant?"
    )
    option1 = L1ScreeningQuestionOption.objects.create(
        question=question, option_text="Yes", option_value="yes_def"
    )
    option2 = L1ScreeningQuestionOption.objects.create(
        question=question, option_text="No", option_value="no_def"
    )

    prompt_builder = L1ScreeningPromptBuilder(question=question, citation=row)
    prompt_args = prompt_builder.get_screening_prompt_args()

    assert prompt_args.question == "Is this relevant?"

    assert "Title: Test Title" in prompt_args.citation
    assert "Abstract: Test Abstract" in prompt_args.citation
    assert "custom_col1: Custom Value 1" in prompt_args.citation
    assert "custom_col2" not in prompt_args.citation
    assert "Custom Value 2" not in prompt_args.citation

    assert "0. Yes" in prompt_args.options
    assert "1. No" in prompt_args.options

    assert "<Yes>\nyes_def\n</Yes>" in prompt_args.definitions
    assert "<No>\nno_def\n</No>" in prompt_args.definitions

    prompt_str = prompt_builder.build_str()
