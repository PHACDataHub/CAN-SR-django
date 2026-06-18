from django.test import override_settings

import pytest

from my_app.models import LanguageModel

pytestmark = pytest.mark.backend


def test_get_supported_models_for_env_returns_active_models_in_order():
    LanguageModel.objects.filter(supported_env="ollama").update(
        is_active=False
    )
    later = LanguageModel.objects.create(
        name="Later",
        key="later",
        deployment="later",
        order=20,
        supported_env="ollama",
    )
    earlier = LanguageModel.objects.create(
        name="Earlier",
        key="earlier",
        deployment="earlier",
        order=10,
        supported_env="ollama",
    )
    LanguageModel.objects.create(
        name="Inactive",
        key="inactive",
        deployment="inactive",
        is_active=False,
        order=1,
        supported_env="ollama",
    )

    models = list(LanguageModel.get_supported_models_for_env("ollama"))

    assert models == [earlier, later]


def test_get_supported_models_uses_current_environment():
    with override_settings(LLM_MODE="azure"):
        models = LanguageModel.get_supported_models()

    assert models
    assert all(model.supported_env == "azure" for model in models)


def test_get_default_model_returns_first_supported_default():
    with override_settings(LLM_MODE="azure"):
        model = LanguageModel.get_default_model()

    assert model.key == "gpt-5-mini"


def test_get_default_model_ignores_inactive_default():
    LanguageModel.objects.filter(
        supported_env="azure", is_default=True
    ).update(is_active=False)

    with override_settings(LLM_MODE="azure"):
        model = LanguageModel.get_default_model()

    assert model is None
