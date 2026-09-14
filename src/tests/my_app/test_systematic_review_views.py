from django.test import override_settings
from django.urls import reverse

import pytest
from autocomplete import AutocompleteWidget
from phac_aspc.rules import patch_rules

from my_app.autocompletes import UserAutocomplete
from my_app.model_factories import (
    CitationDatasetFactory,
    L1ScreeningQuestionFactory,
    ReviewFactory,
    ReviewUserLinkFactory,
    UserFactory,
)
from my_app.models import (
    CitationDataset,
    L1ScreeningQuestion,
    LanguageModel,
    Review,
    ReviewUserLink,
)
from my_app.views.review import ReviewForm

pytestmark = pytest.mark.view


@override_settings(LLM_MODE="ollama")
def test_review_form_only_lists_supported_models_and_labels_default():
    LanguageModel.objects.filter(supported_env="ollama").update(
        is_active=False
    )
    default_model = LanguageModel.objects.create(
        name="Default model",
        key="default-model",
        deployment="default-model",
        supported_env="ollama",
        is_default=True,
    )
    supported_model = LanguageModel.objects.create(
        name="Supported model",
        key="supported-model",
        deployment="supported-model",
        supported_env="ollama",
    )
    LanguageModel.objects.create(
        name="Inactive model",
        key="inactive-model",
        deployment="inactive-model",
        supported_env="ollama",
        is_active=False,
    )

    field = ReviewForm().fields["language_model"]

    assert list(field.queryset) == [default_model, supported_model]
    assert field.empty_label == "Default (currently Default model)"


def test_review_form_uses_multiselect_user_autocomplete():
    field = ReviewForm().fields["users"]

    assert isinstance(field.widget, AutocompleteWidget)
    assert field.widget.ac_class is UserAutocomplete
    assert field.widget.config == {
        "multiselect": True,
        "placeholder": "search for users",
    }
    assert not field.required


def test_review_form_only_includes_is_deleted_field_when_editing():
    assert "is_deleted" not in ReviewForm().fields

    field = ReviewForm(instance=ReviewFactory()).fields["is_deleted"]
    assert not field.required


def test_review_form_initially_selects_non_admin_creator(vanilla_user):
    with patch_rules(is_admin=False):
        form = ReviewForm(request_user=vanilla_user)

    assert form.initial["users"] == [vanilla_user]


def test_review_form_does_not_initially_select_admin_creator(admin_user):
    with patch_rules(is_admin=True):
        form = ReviewForm(request_user=admin_user)

    assert "users" not in form.initial


def test_create_review_creates_link_and_redirects(
    vanilla_user_client, vanilla_user
):
    url = reverse("create_review")
    response = vanilla_user_client.get(url)
    assert response.status_code == 200

    good_data = {
        "title": "Test systematic review",
        "description": "This is a test systematic review.",
    }

    response = vanilla_user_client.post(url, good_data)
    assert response.status_code == 302

    review = Review.objects.get(title="Test systematic review")
    assert response.url == reverse("review_detail", args=[review.id])
    assert ReviewUserLink.objects.filter(
        user=vanilla_user, review=review
    ).exists()

    body = vanilla_user_client.get(url).content.decode()
    assert "Systematic Reviews" in body
    assert "Create systematic review" in body
    assert "Cancel" not in body


def test_create_review_saves_selected_users_and_creator(
    vanilla_user_client, vanilla_user
):
    selected_user = UserFactory()

    response = vanilla_user_client.post(
        reverse("create_review"),
        {
            "title": "Review with users",
            "description": "Description",
            "users": [selected_user.id],
        },
    )

    assert response.status_code == 302
    review = Review.objects.get(title="Review with users")
    assert set(review.users.all()) == {vanilla_user, selected_user}


def test_edit_review_requires_non_admin_to_retain_access(
    vanilla_user_client, vanilla_user
):
    review = ReviewFactory()
    ReviewUserLinkFactory(user=vanilla_user, review=review)

    response = vanilla_user_client.post(
        reverse("edit_review", args=[review.id]),
        {
            "title": review.title,
            "description": review.description,
            "users": [],
        },
    )

    assert response.status_code == 200
    assert response.context["form"].errors["users"] == [
        "You must include yourself as an author."
    ]
    assert review.users.filter(pk=vanilla_user.pk).exists()


def test_admin_can_remove_all_review_users(admin_client):
    review = ReviewFactory()
    linked_user = UserFactory()
    ReviewUserLinkFactory(user=linked_user, review=review)

    response = admin_client.post(
        reverse("edit_review", args=[review.id]),
        {
            "title": review.title,
            "description": review.description,
            "users": [],
        },
    )

    assert response.status_code == 302
    assert not review.users.exists()


def test_edit_review_uses_rule(vanilla_user_client, vanilla_user):
    review = ReviewFactory()
    ReviewUserLinkFactory(user=vanilla_user, review=review)

    url = reverse("edit_review", args=[review.id])

    with patch_rules(can_access_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(url)
        assert response.status_code == 200
        body = response.content.decode()
        assert "Systematic Reviews" in body
        assert review.title in body
        assert "Edit review" in body
        assert "Cancel" not in body


def test_edit_review_only_shows_danger_zone_when_user_can_hard_delete(
    vanilla_user_client, vanilla_user
):
    review = ReviewFactory()
    ReviewUserLinkFactory(user=vanilla_user, review=review)
    url = reverse("edit_review", args=[review.id])

    with patch_rules(can_access_review=True, can_hard_delete_review=False):
        response = vanilla_user_client.get(url)

    assert "Danger zone" not in response.content.decode()

    with patch_rules(can_access_review=True, can_hard_delete_review=True):
        response = vanilla_user_client.get(url)

    body = response.content.decode()
    assert "Danger zone" in body
    assert reverse("hard_delete_review", args=[review.id]) in body


def test_hard_delete_review_requires_rule(vanilla_user_client):
    review = ReviewFactory()
    url = reverse("hard_delete_review", args=[review.id])

    with patch_rules(can_hard_delete_review=False):
        assert vanilla_user_client.get(url).status_code == 403
        assert (
            vanilla_user_client.post(url, {"confirm": True}).status_code == 403
        )

    assert Review.objects.filter(pk=review.pk).exists()


def test_hard_delete_review_requires_confirmation(vanilla_user_client):
    review = ReviewFactory()
    url = reverse("hard_delete_review", args=[review.id])

    with patch_rules(can_hard_delete_review=True):
        response = vanilla_user_client.post(url, {})

    assert response.status_code == 200
    assert "This field is required." in response.content.decode()
    assert Review.objects.filter(pk=review.pk).exists()


def test_hard_delete_review_cascades_and_redirects(vanilla_user_client):
    review = ReviewFactory()
    ReviewUserLinkFactory(review=review)
    dataset = CitationDatasetFactory(review=review)
    question = L1ScreeningQuestionFactory(review=review)
    review_id = review.id
    url = reverse("hard_delete_review", args=[review_id])

    with patch_rules(can_hard_delete_review=True):
        response = vanilla_user_client.post(
            url,
            {"confirm": True},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert response["HX-Redirect"] == reverse("review_list")
    assert not Review.objects.filter(pk=review_id).exists()
    assert not ReviewUserLink.objects.filter(review_id=review_id).exists()
    assert not CitationDataset.objects.filter(pk=dataset.pk).exists()
    assert not L1ScreeningQuestion.objects.filter(pk=question.pk).exists()


def test_detail_review_uses_rule(vanilla_user_client, vanilla_user):
    review = ReviewFactory()
    ReviewUserLinkFactory(user=vanilla_user, review=review)

    url = reverse("review_detail", args=[review.id])

    with patch_rules(can_access_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(url)
        assert response.status_code == 200
        body = response.content.decode()
        assert "Systematic Reviews" in body
        assert review.title in body


def test_detail_review_links_to_upload_when_dataset_missing(
    vanilla_user_client, vanilla_user
):
    review = ReviewFactory()
    ReviewUserLinkFactory(user=vanilla_user, review=review)

    with patch_rules(can_access_review=True):
        body = vanilla_user_client.get(
            reverse("review_detail", args=[review.id])
        ).content.decode()

    assert reverse("citation_upload", args=[review.id]) in body
    assert "Upload dataset" in body


def test_deleted_review_detail_shows_archive_warning_and_breadcrumb(
    vanilla_user_client, vanilla_user
):
    review = ReviewFactory(title="Archived review", is_deleted=True)
    ReviewUserLinkFactory(user=vanilla_user, review=review)

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(
            reverse("review_detail", args=[review.id])
        )

    assert response.status_code == 200
    body = response.content.decode()
    assert "This review is archived." in body
    assert "Archived review (ARCHIVED)" in body


def test_screening_criteria_page_uses_rule_and_detail_links_to_it(
    vanilla_user_client, vanilla_user
):
    review = ReviewFactory()
    ReviewUserLinkFactory(user=vanilla_user, review=review)

    url = reverse("screening_criteria", args=[review.id])

    with patch_rules(can_access_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(url)
        assert response.status_code == 200
        body = response.content.decode()
        assert "Systematic Reviews" in body
        assert review.title in body
        assert "Screening criteria" in body


def test_list_reviews_only_shows_linked_reviews_for_user(
    vanilla_user_client, vanilla_user
):
    linked_review = ReviewFactory(title="Linked review")
    other_review = ReviewFactory(title="Other review")
    ReviewUserLinkFactory(user=vanilla_user, review=linked_review)

    url = reverse("review_list")
    with patch_rules(is_admin=False):
        response = vanilla_user_client.get(url)

    assert response.status_code == 200
    object_ids = [review.id for review in response.context["object_list"]]
    assert object_ids == [linked_review.id]

    body = response.content.decode()
    assert "Linked review" in body
    assert other_review.title not in body
    assert "Systematic Reviews" in body


def test_admin_sees_all_reviews(vanilla_user_client):
    ReviewFactory(title="First review")
    ReviewFactory(title="Second review")

    url = reverse("review_list")
    with patch_rules(is_admin=True):
        response = vanilla_user_client.get(url)

    assert response.status_code == 200
    assert len(response.context["object_list"]) == 2
    body = response.content.decode()
    assert "Systematic Reviews" in body


@pytest.mark.parametrize("is_admin", [False, True])
def test_list_reviews_hides_deleted_reviews(
    vanilla_user_client, vanilla_user, is_admin
):
    active_review = ReviewFactory(title="Active review")
    deleted_review = ReviewFactory(title="Deleted review", is_deleted=True)
    ReviewUserLinkFactory(user=vanilla_user, review=active_review)
    ReviewUserLinkFactory(user=vanilla_user, review=deleted_review)

    with patch_rules(is_admin=is_admin):
        response = vanilla_user_client.get(reverse("review_list"))

    object_ids = [review.id for review in response.context["object_list"]]
    assert active_review.id in object_ids
    assert deleted_review.id not in object_ids
    assert "Active review" in response.content.decode()
    assert "Deleted review" not in response.content.decode()
