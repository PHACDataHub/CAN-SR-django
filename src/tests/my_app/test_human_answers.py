from my_app.model_factories import (
    L1HumanAnswerFactory,
    L2HumanAnswerFactory,
    ParameterHumanAnswerFactory,
)
from my_app.models import (
    L1HumanAnswer,
    L2HumanAnswer,
    ParameterExtractionResult,
    ParameterHumanAnswer,
)


def test_human_answer_flavors_are_decoupled_and_allow_duplicates():
    for factory, model in (
        (L1HumanAnswerFactory, L1HumanAnswer),
        (L2HumanAnswerFactory, L2HumanAnswer),
        (ParameterHumanAnswerFactory, ParameterHumanAnswer),
    ):
        answer = factory()
        duplicate_fields = {
            "citation": answer.citation,
            "question": answer.question,
            "user": answer.user,
        }
        if hasattr(answer, "selected_option"):
            duplicate_fields["selected_option"] = answer.selected_option
        else:
            duplicate_fields["found"] = answer.found
            duplicate_fields["value"] = answer.value

        model.objects.create(**duplicate_fields)

        assert model.objects.count() == 2
        assert not model._meta.unique_together
        assert not hasattr(answer, "status")
        assert not hasattr(answer, "language_model")


def test_parameter_result_has_no_human_answer_fields():
    result = ParameterExtractionResult()

    assert not hasattr(result, "human_found")
    assert not hasattr(result, "human_value")
