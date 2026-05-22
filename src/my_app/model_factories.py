import factory

from proj.models import User

from my_app.models import (
    DemoTaskRun,
    CitationDataset,
    CitationDatasetColumn,
    CitationDatasetRow,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    ParameterQuestion,
    ParameterQuestionOption,
    ParameterExtractionResult,
    ScreeningResultStatus,
    SystematicReview,
    SystematicReviewUserLink,
)


class DemoTaskRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DemoTaskRun

    task_result_id = factory.Faker("uuid4")
    kind = "sync"
    label = factory.Faker("word")
    record_count = factory.Faker("random_int")
    attempt = 1


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")


class SystematicReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SystematicReview

    title = factory.Faker("sentence", nb_words=4)
    description = factory.Faker("text")


class SystematicReviewUserLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SystematicReviewUserLink

    user = factory.SubFactory(UserFactory)
    systematic_review = factory.SubFactory(SystematicReviewFactory)


class CitationDatasetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CitationDataset

    systematic_review = factory.SubFactory(SystematicReviewFactory)


class CitationDatasetColumnFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CitationDatasetColumn

    dataset = factory.SubFactory(CitationDatasetFactory)
    name = factory.Sequence(lambda n: f"Column {n + 1}")


class CitationDatasetRowFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CitationDatasetRow

    dataset = factory.SubFactory(CitationDatasetFactory)
    order = factory.Sequence(lambda n: n + 1)
    title = factory.LazyAttribute(lambda obj: f"Citation {obj.order}")
    abstract = factory.Faker("sentence")


class L1ScreeningQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L1ScreeningQuestion

    review = factory.SubFactory(SystematicReviewFactory)
    question_text = factory.Sequence(
        lambda n: f"Is this citation relevant? {n + 1}"
    )


class L1ScreeningQuestionOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L1ScreeningQuestionOption

    question = factory.SubFactory(L1ScreeningQuestionFactory)
    option_text = factory.Sequence(lambda n: f"Option {n + 1}")
    option_value = factory.Faker("sentence")


class L2ScreeningQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L2ScreeningQuestion

    review = factory.SubFactory(SystematicReviewFactory)
    question_text = factory.Sequence(
        lambda n: f"Is this citation eligible? {n + 1}"
    )


class L2ScreeningQuestionOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L2ScreeningQuestionOption

    question = factory.SubFactory(L2ScreeningQuestionFactory)
    option_text = factory.Sequence(lambda n: f"Option {n + 1}")
    option_value = factory.Faker("sentence")


class ParameterQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterQuestion

    review = factory.SubFactory(SystematicReviewFactory)
    question_text = factory.Sequence(lambda n: f"Parameter question {n + 1}")


class ParameterQuestionOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterQuestionOption

    question = factory.SubFactory(ParameterQuestionFactory)
    param_name = factory.Sequence(lambda n: f"Parameter {n + 1}")
    param_description = factory.Faker("sentence")


class L1ScreeningResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L1ScreeningResult

    citation = factory.SubFactory(CitationDatasetRowFactory)
    question = factory.SubFactory(
        L1ScreeningQuestionFactory,
        review=factory.SelfAttribute("..citation.dataset.systematic_review"),
    )
    selected_option = None
    status = ScreeningResultStatus.PENDING


class L2ScreeningResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L2ScreeningResult

    citation = factory.SubFactory(CitationDatasetRowFactory)
    question = factory.SubFactory(
        L2ScreeningQuestionFactory,
        review=factory.SelfAttribute("..citation.dataset.systematic_review"),
    )
    selected_option = None
    status = ScreeningResultStatus.PENDING


class ParameterExtractionResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterExtractionResult

    citation = factory.SubFactory(CitationDatasetRowFactory)
    question = factory.SubFactory(
        ParameterQuestionFactory,
        review=factory.SelfAttribute("..citation.dataset.systematic_review"),
    )
    selected_option = None
    status = ScreeningResultStatus.PENDING
