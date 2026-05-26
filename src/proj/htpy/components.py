import htpy
import htpy as h
from data_fetcher.util import get_request
from htpy import Node, Renderable

from proj.text import tdt, tm


def get_csrf_token():
    request = get_request()
    token = request.META.get("CSRF_COOKIE", "")
    return token


def CsrfInput() -> Node:
    token = get_csrf_token()
    return htpy.input(type="hidden", name="csrfmiddlewaretoken", value=token)


def JsonDisplay(value) -> Renderable:
    return _render_json_value(value)


def _render_json_value(value):
    if isinstance(value, dict):
        if not value:
            return h.span(".text-muted")[tdt("Empty")]
        return h.dl(".row.mb-0")[
            [
                rendered
                for key, item in value.items()
                for rendered in (
                    h.dt(".col-sm-4.mb-0")[key],
                    h.dd(".col-sm-8.mb-0")[_render_json_value(item)],
                )
            ]
        ]

    if isinstance(value, list):
        if not value:
            return h.span(".text-muted")[tdt("Empty")]
        return h.ul(".mb-0.ps-3")[
            [h.li[_render_json_value(item)] for item in value]
        ]

    if value is None:
        return h.span(".text-muted")["null"]

    if isinstance(value, bool):
        return tm("yes") if value else tm("no")

    if isinstance(value, (int, float)):
        return str(value)

    return value
