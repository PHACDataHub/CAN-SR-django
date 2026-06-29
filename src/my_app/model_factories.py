import factory

from proj.models import User

from my_app.models import (
    Citation,
    CitationDataset,
    CitationDatasetColumn,
    DemoTaskRun,
    Document,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    Parameter,
    ParameterCategory,
    ParameterExtractionResult,
    Review,
    ReviewUserLink,
    ScreeningResultStatus,
    TextExtractionResult,
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


class ReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Review

    title = factory.Faker("sentence", nb_words=4)
    description = factory.Faker("text")
    language_model = None


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    file = factory.django.FileField(
        filename="example.pdf",
        data=b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
    )


class TextExtractionResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TextExtractionResult

    document = factory.SubFactory(DocumentFactory)


class ReviewUserLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReviewUserLink

    user = factory.SubFactory(UserFactory)
    review = factory.SubFactory(ReviewFactory)


class CitationDatasetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CitationDataset

    review = factory.SubFactory(ReviewFactory)


class CitationDatasetColumnFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CitationDatasetColumn

    dataset = factory.SubFactory(CitationDatasetFactory)
    name = factory.Sequence(lambda n: f"Column {n + 1}")


class CitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Citation

    dataset = factory.SubFactory(CitationDatasetFactory)
    order = factory.Sequence(lambda n: n + 1)
    title = factory.LazyAttribute(lambda obj: f"Citation {obj.order}")
    abstract = factory.Faker("sentence")


class L1ScreeningQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L1ScreeningQuestion

    review = factory.SubFactory(ReviewFactory)
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

    review = factory.SubFactory(ReviewFactory)
    question_text = factory.Sequence(
        lambda n: f"Is this citation eligible? {n + 1}"
    )


class L2ScreeningQuestionOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L2ScreeningQuestionOption

    question = factory.SubFactory(L2ScreeningQuestionFactory)
    option_text = factory.Sequence(lambda n: f"Option {n + 1}")
    option_value = factory.Faker("sentence")


class ParameterCategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterCategory

    review = factory.SubFactory(ReviewFactory)
    name = factory.Sequence(lambda n: f"Parameter category {n + 1}")


class ParameterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Parameter

    category = factory.SubFactory(ParameterCategoryFactory)
    name = factory.Sequence(lambda n: f"Parameter {n + 1}")
    description = factory.Faker("sentence")


class L1ScreeningResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L1ScreeningResult

    citation = factory.SubFactory(CitationFactory)
    question = factory.SubFactory(
        L1ScreeningQuestionFactory,
        review=factory.SelfAttribute("..citation.dataset.review"),
    )
    selected_option = None
    status = ScreeningResultStatus.PENDING


class L2ScreeningResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L2ScreeningResult

    citation = factory.SubFactory(CitationFactory)
    question = factory.SubFactory(
        L2ScreeningQuestionFactory,
        review=factory.SelfAttribute("..citation.dataset.review"),
    )
    selected_option = None
    status = ScreeningResultStatus.PENDING


class ParameterExtractionResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterExtractionResult

    citation = factory.SubFactory(CitationFactory)
    question = factory.SubFactory(
        ParameterFactory,
        category__review=factory.SelfAttribute("..citation.dataset.review"),
    )
    status = ScreeningResultStatus.PENDING
