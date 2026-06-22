from django.test import override_settings

import pytest

from my_app.model_factories import ReviewFactory
from my_app.models import LanguageModel
from my_app.queries import get_model_for_review

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


@override_settings(LLM_MODE="ollama")
def test_get_model_for_review_returns_selected_supported_model():
    selected_model = LanguageModel.objects.create(
        name="Selected",
        key="selected",
        deployment="selected",
        supported_env="ollama",
    )
    review = ReviewFactory(language_model=selected_model)

    assert get_model_for_review(review.id) == selected_model


@override_settings(LLM_MODE="ollama")
def test_get_model_for_review_returns_default_when_none_selected():
    LanguageModel.objects.filter(supported_env="ollama").update(
        is_default=False
    )
    default_model = LanguageModel.objects.create(
        name="Default",
        key="default",
        deployment="default",
        supported_env="ollama",
        is_default=True,
    )
    review = ReviewFactory(language_model=None)

    assert get_model_for_review(review.id) == default_model


@override_settings(LLM_MODE="ollama")
def test_get_model_for_review_logs_and_falls_back_for_unsupported_model(
    caplog,
):
    LanguageModel.objects.filter(supported_env="ollama").update(
        is_default=False
    )
    default_model = LanguageModel.objects.create(
        name="Default",
        key="default",
        deployment="default",
        supported_env="ollama",
        is_default=True,
    )
    unsupported_model = LanguageModel.objects.create(
        name="Unsupported",
        key="unsupported",
        deployment="unsupported",
        supported_env="azure",
    )
    review = ReviewFactory(language_model=unsupported_model)

    assert get_model_for_review(review.id) == default_model
    assert "unsupported or inactive language model" in caplog.text
