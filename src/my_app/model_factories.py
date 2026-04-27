import factory

from my_app.models import (
    DemoTaskRun,
    Project,
    ProjectTag,
    ProjectTask,
    ProjectType,
)


class ProjectTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectType

    name_en = factory.Faker("word")
    name_fr = factory.Faker("word")
    description_en = factory.Faker("text")
    description_fr = factory.Faker("text")


class ProjectTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectTag

    name_en = factory.Faker("word")
    name_fr = factory.Faker("word")
    description_en = factory.Faker("text")
    description_fr = factory.Faker("text")


class ProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Project

    name_en = factory.Faker("word")
    name_fr = factory.Faker("word")
    description_en = factory.Faker("text")
    description_fr = factory.Faker("text")
    project_type = factory.Iterator(ProjectType.objects.all())


class ProjectTaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectTask

    project = factory.SubFactory(ProjectFactory)
    name_en = factory.Faker("word")
    name_fr = factory.Faker("word")
    description_en = factory.Faker("text")
    description_fr = factory.Faker("text")


class DemoTaskRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DemoTaskRun

    task_result_id = factory.Faker("uuid4")
    kind = "sync"
    label = factory.Faker("word")
    project_count = factory.Faker("random_int")
    attempt = 1
