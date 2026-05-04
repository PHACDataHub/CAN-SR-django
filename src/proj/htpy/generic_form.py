from django.middleware.csrf import get_token

import htpy as h
from data_fetcher.util import get_request
from markupsafe import Markup

from proj.text import tm

from .util import HtpyComponent


class GenericForm(HtpyComponent):
    def __init__(self, form, csrf_token):
        super().__init__()
        self.form = form
        self.csrf_token = csrf_token

    def render(self):
        form = self.form
        return [
            Markup(str(form.media)),
            Markup(
                f'<input type="hidden" name="csrfmiddlewaretoken" value="{self.csrf_token}">'
            ),
            h.div(".mt-3")[
                [
                    [Markup(str(field.errors)), Markup(str(field))]
                    for field in form.hidden_fields()
                ],
                [
                    [
                        (
                            h.div(".alert.alert-danger")[
                                Markup(str(field.errors))
                            ]
                            if field.errors
                            else None
                        ),
                        h.label(".row.mb-3")[
                            h.div(".col-sm-3.col-form-label")[
                                h.div[
                                    h.strong[
                                        (
                                            h.span(".text-danger")["*"]
                                            if field.field.required
                                            else None
                                        ),
                                        Markup(str(field.label_tag())),
                                    ],
                                ],
                                (
                                    h.div(".transparent-text")[
                                        Markup(str(field.help_text))
                                    ]
                                    if field.help_text
                                    else None
                                ),
                            ],
                            h.div(".col-sm-9")[Markup(str(field))],
                        ],
                    ]
                    for field in form.visible_fields()
                ],
            ],
        ]


def GenericFormWithContainer(
    form,
    form_attrs=None,
    submit_label=None,
):

    if not submit_label:
        submit_label = tm("submit")

    token = get_token(get_request())

    if not form_attrs:
        form_attrs = {
            "method": "post",
        }

    return h.form(form_attrs)[
        GenericForm(form, token).render(),
        h.div(".text-end")[
            h.button(
                ".btn.btn-success.btn-lg",
                type="submit",
            )[submit_label],
        ],
    ]
