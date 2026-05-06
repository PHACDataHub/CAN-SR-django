from django.urls import reverse

from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    SystematicReviewFactory,
    SystematicReviewUserLinkFactory,
)
from my_app.models import SystematicReview, SystematicReviewUserLink


def test_create_systematic_review_creates_link_and_redirects(
    vanilla_user_client, vanilla_user
):
    url = reverse("create_systematic_review")
    response = vanilla_user_client.get(url)
    assert response.status_code == 200

    good_data = {
        "title": "Test systematic review",
        "description": "This is a test systematic review.",
    }

    response = vanilla_user_client.post(url, good_data)
    assert response.status_code == 302

    review = SystematicReview.objects.get(title="Test systematic review")
    assert response.url == reverse(
        "systematic_review_detail", args=[review.id]
    )
    assert SystematicReviewUserLink.objects.filter(
        user=vanilla_user, systematic_review=review
    ).exists()

    body = vanilla_user_client.get(url).content.decode()
    assert "Systematic Reviews" in body
    assert "Create systematic review" in body
    assert "Cancel" not in body


def test_edit_systematic_review_uses_rule(vanilla_user_client, vanilla_user):
    review = SystematicReviewFactory()
    SystematicReviewUserLinkFactory(
        user=vanilla_user, systematic_review=review
    )

    url = reverse("edit_systematic_review", args=[review.id])

    with patch_rules(can_access_systematic_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.get(url)
        assert response.status_code == 200
        body = response.content.decode()
        assert "Systematic Reviews" in body
        assert review.title in body
        assert "Edit systematic review" in body
        assert "Cancel" not in body


def test_detail_systematic_review_uses_rule(vanilla_user_client, vanilla_user):
    review = SystematicReviewFactory()
    SystematicReviewUserLinkFactory(
        user=vanilla_user, systematic_review=review
    )

    url = reverse("systematic_review_detail", args=[review.id])

    with patch_rules(can_access_systematic_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.get(url)
        assert response.status_code == 200
        body = response.content.decode()
        assert "Systematic Reviews" in body
        assert review.title in body


def test_screening_criteria_page_uses_rule_and_detail_links_to_it(
    vanilla_user_client, vanilla_user
):
    review = SystematicReviewFactory()
    SystematicReviewUserLinkFactory(
        user=vanilla_user, systematic_review=review
    )

    url = reverse("screening_criteria", args=[review.id])

    with patch_rules(can_access_systematic_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.get(url)
        assert response.status_code == 200
        body = response.content.decode()
        assert "Systematic Reviews" in body
        assert review.title in body
        assert "Screening criteria" in body

    with patch_rules(can_access_systematic_review=True):
        detail_body = vanilla_user_client.get(
            reverse("systematic_review_detail", args=[review.id])
        ).content.decode()

    assert url in detail_body
    assert "Screening criteria" in detail_body


def test_list_systematic_reviews_only_shows_linked_reviews_for_user(
    vanilla_user_client, vanilla_user
):
    linked_review = SystematicReviewFactory(title="Linked review")
    other_review = SystematicReviewFactory(title="Other review")
    SystematicReviewUserLinkFactory(
        user=vanilla_user, systematic_review=linked_review
    )

    url = reverse("systematic_review_list")
    with patch_rules(is_admin=False):
        response = vanilla_user_client.get(url)

    assert response.status_code == 200
    object_ids = [review.id for review in response.context["object_list"]]
    assert object_ids == [linked_review.id]

    body = response.content.decode()
    assert "Linked review" in body
    assert other_review.title not in body
    assert "Systematic Reviews" in body


def test_admin_sees_all_systematic_reviews(vanilla_user_client):
    SystematicReviewFactory(title="First review")
    SystematicReviewFactory(title="Second review")

    url = reverse("systematic_review_list")
    with patch_rules(is_admin=True):
        response = vanilla_user_client.get(url)

    assert response.status_code == 200
    assert len(response.context["object_list"]) == 2
    body = response.content.decode()
    assert "Systematic Reviews" in body
