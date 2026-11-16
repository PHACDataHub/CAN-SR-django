import htpy as h

from proj.htpy.modal_component import ModalComponent
from proj.text import tdt


def DeleteConfirmation(title, message, post_url, *, error=None):
    form_id = "delete-confirmation-form"
    footer = h.fragment[
        h.button(".btn.btn-secondary", type="button", data_modal_close=True)[
            tdt("Cancel")
        ],
        h.button(
            ".btn.btn-danger",
            type="submit",
            form=form_id,
            hx_disabled_elt="this",
        )[title],
    ]
    return ModalComponent(
        title=title, modal_id="delete-confirmation-modal", footer=footer
    )[
        h.form(
            id=form_id,
            hx_post=post_url,
            hx_target="#modal-slot",
            hx_swap="innerHTML",
        )[
            h.p(".text-danger", role="alert")[error] if error else None,
            h.p(".mb-0")[message],
        ]
    ]
