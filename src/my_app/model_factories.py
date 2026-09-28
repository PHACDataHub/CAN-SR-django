import factory

from proj.models import User

from my_app.models import (
    Citation,
    CitationDataset,
    CitationDatasetColumn,
    Document,
    FigureExtractionResult,
    L1HumanAnswer,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    L2HumanAnswer,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    ParameterOption,
    Review,
    ReviewUserLink,
    ScreeningResultStatus,
    TextExtractionResult,
)


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


class FigureExtractionResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FigureExtractionResult

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


class ParameterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Parameter

    review = factory.SubFactory(ReviewFactory)
    name = factory.Sequence(lambda n: f"Parameter {n + 1}")
    description = factory.Faker("sentence")


class ParameterOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterOption

    parameter = factory.SubFactory(ParameterFactory)
    name = factory.Sequence(lambda n: f"Parameter option {n + 1}")
    context = factory.Faker("sentence")


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


class L1HumanAnswerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L1HumanAnswer

    citation = factory.SubFactory(CitationFactory)
    question = factory.SubFactory(
        L1ScreeningQuestionFactory,
        review=factory.SelfAttribute("..citation.dataset.review"),
    )
    selected_option = factory.SubFactory(
        L1ScreeningQuestionOptionFactory,
        question=factory.SelfAttribute("..question"),
    )
    user = factory.SubFactory(UserFactory)


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


class L2HumanAnswerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = L2HumanAnswer

    citation = factory.SubFactory(CitationFactory)
    question = factory.SubFactory(
        L2ScreeningQuestionFactory,
        review=factory.SelfAttribute("..citation.dataset.review"),
    )
    selected_option = factory.SubFactory(
        L2ScreeningQuestionOptionFactory,
        question=factory.SelfAttribute("..question"),
    )
    user = factory.SubFactory(UserFactory)


class ParameterExtractionResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterExtractionResult

    citation = factory.SubFactory(CitationFactory)
    question = factory.SubFactory(
        ParameterFactory,
        review=factory.SelfAttribute("..citation.dataset.review"),
    )
    status = ScreeningResultStatus.PENDING


class ParameterHumanAnswerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterHumanAnswer

    citation = factory.SubFactory(CitationFactory)
    question = factory.SubFactory(
        ParameterFactory,
        review=factory.SelfAttribute("..citation.dataset.review"),
    )
    user = factory.SubFactory(UserFactory)
