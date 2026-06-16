from urllib.parse import parse_qsl, urlparse

from django.test import RequestFactory

import pytest

from my_app.views.view_utils import url_with_same_params

pytestmark = pytest.mark.backend


def test_url_with_same_params_preserves_existing_params_and_can_override_path():
    request = RequestFactory().get(
        "/screening-l1/?status=pending&page=2&filter=full"
    )

    same_path_url = url_with_same_params(request, page=3)
    overridden_path_url = url_with_same_params(
        request,
        path="/screening-l1/component/",
        page=3,
    )

    assert urlparse(same_path_url).path == "/screening-l1/"
    assert parse_qsl(urlparse(same_path_url).query) == [
        ("status", "pending"),
        ("filter", "full"),
        ("page", "3"),
    ]

    assert urlparse(overridden_path_url).path == "/screening-l1/component/"
    assert parse_qsl(urlparse(overridden_path_url).query) == [
        ("status", "pending"),
        ("filter", "full"),
        ("page", "3"),
    ]
