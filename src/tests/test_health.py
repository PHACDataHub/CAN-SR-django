from django.test import Client
from django.urls import reverse


def test_liveness_does_not_require_authentication(settings):
    settings.ALLOWED_HOSTS.append("testserver")
    response = Client().get(reverse("health_live"))

    assert response.status_code == 200
    assert response.content == b"ok"
    assert response["Content-Type"] == "text/plain"
