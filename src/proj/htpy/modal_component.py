import htpy
import htpy as h
from htpy import Node, Renderable

from proj.text import tdt, tm


@h.with_children
def ModalComponent(
    children,
    *,
    title=None,
    size_cls=None,
    modal_id=None,
    close_button_text=None,
    footer=None,
    header=None,
):

    if close_button_text is None:
        close_button_text = tm("close")

    if size_cls is None:
        size_cls = "modal-lg"

    wrapper_attrs = {
        "data_modal": True,
        "aria_hidden": "true",
        "class": ["modal", size_cls],
    }
    if modal_id:
        wrapper_attrs["id"] = modal_id

    if footer is None:
        footer = (
            h.button(
                type="button",
                class_="btn btn-secondary",
                data_modal_close=True,
            )[close_button_text],
        )

    if header is None:
        header = h.fragment[
            h.h1(".modal-title.fs-5")[title],
            h.button(
                type="button",
                class_="btn-close",
                data_modal_close=True,
                aria_label="Close",
            ),
        ]

    return h.div(**wrapper_attrs)[
        h.div(
            class_=[
                "modal-dialog",
            ]
        )[
            h.div(".modal-content")[
                h.div(".modal-header")[header],
                h.div(".modal-body")[children],
                h.div(".modal-footer")[footer],
            ],
        ],
    ]
