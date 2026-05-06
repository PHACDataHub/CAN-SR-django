import factory

from proj.models import User

from my_app.models import (
    DemoTaskRun,
    SystematicReview,
    SystematicReviewUserLink,
    ScreeningQuestion,
    ScreeningQuestionOption,
    ParameterQuestion,
    ParameterQuestionOption,
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


class ScreeningQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScreeningQuestion

    review = factory.SubFactory(SystematicReviewFactory)
    screening_type = ScreeningQuestion.ScreeningType.L1
    question_text = factory.Faker("sentence")


class ScreeningQuestionOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScreeningQuestionOption

    question = factory.SubFactory(ScreeningQuestionFactory)
    option_text = factory.Faker("sentence")
    option_value = factory.Faker("text")


class ParameterQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterQuestion

    review = factory.SubFactory(SystematicReviewFactory)
    question_text = factory.Faker("sentence")


class ParameterQuestionOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ParameterQuestionOption

    question = factory.SubFactory(ParameterQuestionFactory)
    option_text = factory.Faker("sentence")
    option_value = factory.Faker("text")
