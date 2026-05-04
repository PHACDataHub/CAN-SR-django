import factory

from proj.models import User

from my_app.models import (
    DemoTaskRun,
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
