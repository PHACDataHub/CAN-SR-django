from typing import Any, Iterable

import htpy as h

from proj.text import tdt, tm


def render_dl_value(value):
    """
    external helper to wrap common python values
    in appropriate HTML for display in a definition list
    """
    if isinstance(value, dict):
        if not value:
            return h.span(".text-muted")[tdt("Empty")]

        return h.dl(".row.mb-0")[
            [
                rendered
                for key, item in value.items()
                for rendered in (
                    h.dt(".col-sm-4.mb-0")[key],
                    h.dd(".col-sm-8.mb-0")[render_dl_value(item)],
                )
            ]
        ]

    if isinstance(value, list):
        if not value:
            return h.span(".text-muted")[tm("empty")]

        return h.ul(".mb-0.ps-3")[
            [h.li[render_dl_value(item)] for item in value]
        ]

    if value is None:
        return h.span(".text-muted")[tm("null")]

    if isinstance(value, bool):
        return tm("yes") if value else tm("no")

    return value


def DL(items: Iterable[tuple[Any, Any]]) -> h.Node:
    return h.dl(".custom-dl")[
        [
            rendered
            for label, value in items
            for rendered in (
                h.dt()[label],
                h.dd()[value],
            )
        ]
    ]
