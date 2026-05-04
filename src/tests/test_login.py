from django.urls import reverse

from proj.models import User


def is_client_logged_in(client):
    response = client.get("/")
    assert response.status_code == 302
    if response.url == reverse("login"):
        return False

    if response.url == reverse("systematic_review_list"):
        return True

    raise Exception(f"Unexpected redirect to {response.url}")


def test_login_view(client):
    assert not is_client_logged_in(client)

    url = reverse("login")
    response = client.get(url)
    assert response.status_code == 200

    # bad request,
    response = client.post(url, {"username": "bad", "password": "bad"})
    assert response.status_code == 200
    assert response.context["form"].errors

    # create user
    user = User.objects.create_user(username="testuser", password="testpass")
    response = client.post(
        url, {"username": "testuser", "password": "testpass"}
    )
    assert response.status_code == 302
    assert response.url == reverse("systematic_review_list")
    assert is_client_logged_in(client)


def test_logout_view(client):
    user = User.objects.create_user(username="testuser", password="testpass")
    client.login(username="testuser", password="testpass")

    # check actually logged in
    assert is_client_logged_in(client)

    # logout with get
    url = reverse("logout")
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("login")
    assert not is_client_logged_in(client)

    # try again with post
    client.login(username="testuser", password="testpass")
    assert is_client_logged_in(client)

    url = reverse("logout")
    response = client.post(url)
    assert response.status_code == 302
    assert response.url == reverse("login")
    # again, confirm logged out
    assert not is_client_logged_in(client)
