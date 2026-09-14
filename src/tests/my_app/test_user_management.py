from django.contrib.auth.models import Group
from django.urls import reverse

from phac_aspc.rules import patch_rules

from proj.models import User

from my_app.constants import ADMIN_USER_GROUP


def test_user_management_requires_admin(vanilla_client):
    with patch_rules(is_admin=False):
        assert vanilla_client.get(reverse("list_users")).status_code == 403
        assert vanilla_client.get(reverse("create_user")).status_code == 403


def test_list_users(admin_client):
    User.objects.create_user(
        username="person@phac-aspc.gc.ca",
        email="person@phac-aspc.gc.ca",
    )

    response = admin_client.get(reverse("list_users"))

    assert response.status_code == 200
    assert b"person@phac-aspc.gc.ca" in response.content


def test_create_user_with_admin_role(admin_client):
    Group.objects.create(name=ADMIN_USER_GROUP)

    response = admin_client.post(
        reverse("create_user"),
        {
            "email": "Person@phac-aspc.gc.ca",
            "role": ADMIN_USER_GROUP,
        },
    )

    assert response.status_code == 302
    user = User.objects.get(email="person@phac-aspc.gc.ca")
    assert user.username == "person@phac-aspc.gc.ca"
    assert user.groups.get().name == ADMIN_USER_GROUP


def test_create_get_form(admin_client):
    response = admin_client.post(reverse("create_user"))
    assert response.status_code == 200


def test_create_user_with_no_role(admin_client):
    response = admin_client.post(
        reverse("create_user"),
        {
            "email": "person@canada.ca",
            "role": "nil",
        },
    )

    assert response.status_code == 302
    assert not User.objects.get(email="person@canada.ca").groups.exists()


def test_create_user_email_validation(admin_client):
    User.objects.create_user(
        username="existing@phac-aspc.gc.ca",
        email="existing@phac-aspc.gc.ca",
    )
    original_user_count = User.objects.count()

    duplicate_response = admin_client.post(
        reverse("create_user"),
        {
            "email": "Existing@phac-aspc.gc.ca",
            "role": "nil",
        },
    )
    invalid_domain_response = admin_client.post(
        reverse("create_user"),
        {
            "email": "person@example.com",
            "role": "nil",
        },
    )

    assert duplicate_response.status_code == 200
    assert duplicate_response.context["form"].errors["email"]
    assert invalid_domain_response.status_code == 200
    assert invalid_domain_response.context["form"].errors["email"]
    assert User.objects.count() == original_user_count


def test_edit_user_role_preserves_unrelated_groups(admin_client):
    admin_group = Group.objects.create(name=ADMIN_USER_GROUP)
    unrelated_group = Group.objects.create(name="unrelated")
    user = User.objects.create_user(
        username="person", email="person@canada.ca"
    )
    user.groups.add(unrelated_group)
    url = reverse("edit_user", args=[user.pk])

    get_response = admin_client.get(url)
    assert get_response.context["form"].initial["role"] == "nil"

    response = admin_client.post(url, {"role": ADMIN_USER_GROUP})

    assert response.status_code == 302
    assert set(user.groups.values_list("name", flat=True)) == {
        ADMIN_USER_GROUP,
        "unrelated",
    }

    response = admin_client.post(url, {"role": "nil"})

    assert response.status_code == 302
    assert set(user.groups.values_list("name", flat=True)) == {"unrelated"}
    assert Group.objects.filter(pk=admin_group.pk).exists()
