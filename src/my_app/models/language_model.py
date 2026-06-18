from django.conf import settings
from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt


@add_to_admin
class LanguageModel(models.Model):
    class SupportedEnvironment(models.TextChoices):
        LOCAL = "local", tdt("Local")
        OLLAMA = "ollama", tdt("Ollama")
        AZURE = "azure", tdt("Azure")

    class Meta:
        ordering = ["order", "id"]

    name = fields.CharField(max_length=255, verbose_name=tdt("Name"))
    key = fields.CharField(max_length=255, verbose_name=tdt("Key"))
    deployment = fields.CharField(
        max_length=255, verbose_name=tdt("Deployment")
    )
    is_active = fields.BooleanField(
        default=True, verbose_name=tdt("Is active")
    )
    order = fields.IntegerField(default=0, verbose_name=tdt("Order"))
    is_default = fields.BooleanField(
        default=False, verbose_name=tdt("Is default")
    )
    has_multimodal = fields.BooleanField(
        default=False, verbose_name=tdt("Has multimodal support")
    )
    supported_env = fields.CharField(
        max_length=20,
        choices=SupportedEnvironment.choices,
        verbose_name=tdt("Supported environment"),
    )

    def __str__(self):
        return self.name

    @classmethod
    def get_supported_models_for_env(cls, env=None):
        if env is None:
            env = settings.LLM_MODE
        return cls.objects.filter(is_active=True, supported_env=env)

    @classmethod
    def get_supported_models(cls):
        return cls.get_supported_models_for_env(settings.LLM_MODE)

    @classmethod
    def get_default_model(cls):
        return cls.get_supported_models().filter(is_default=True).first()
