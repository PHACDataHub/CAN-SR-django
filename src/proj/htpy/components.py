import htpy
from data_fetcher.util import get_request
from htpy import Node, Renderable


def get_csrf_token():
    request = get_request()
    token = request.META.get("CSRF_COOKIE", "")
    return token


def CsrfInput() -> Node:
    token = get_csrf_token()
    return htpy.input(type="hidden", name="csrfmiddlewaretoken", value=token)
