from django.middleware.csrf import get_token

import htpy as h

from proj.htpy.base_page import BasePageTemplate
from proj.text import tm


class LoginPageTemplate(BasePageTemplate):
    def head_title(self):
        return tm("log_in")

    def content(self):
        form = self.context["form"]
        next_url = self.context.get("next", "")

        return h.div(
            ".container.p-0.d-flex.justify-content-center",
            id="login-container",
        )[
            h.div(".col-md-6.col-sm-12")[
                h.form(
                    method="post",
                    action=self.request.get_full_path(),
                    autocomplete="off",
                )[
                    h.input(
                        type="hidden",
                        name="csrfmiddlewaretoken",
                        value=get_token(self.request),
                    ),
                    (
                        h.div(".alert.alert-warning.fade.show")[
                            h.span[tm("please_login_to_see_page")],
                        ]
                        if next_url
                        else None
                    ),
                    (
                        h.div(
                            ".alert.alert-danger.alert-dismissible.fade.show"
                        )[
                            h.span[tm("bad_user_name_and_password")],
                            h.button(
                                type="button",
                                class_="btn-close",
                                data_bs_dismiss="alert",
                                aria_label=str(tm("close")),
                            ),
                        ]
                        if form.errors
                        else None
                    ),
                    h.div(".card")[
                        h.h2(".card-header")[tm("log_in")],
                        h.div(".card-body")[
                            h.div(".form-floating.mb-3")[
                                h.input(
                                    type="text",
                                    name=form["username"].name,
                                    maxlength="150",
                                    placeholder=str(tm("username")),
                                    required=True,
                                    class_="textinput textInput form-control",
                                ),
                                h.label(
                                    for_=form["username"].id_for_label,
                                )[form["username"].label],
                            ],
                            h.div(".form-floating.mb-3")[
                                h.input(
                                    type="password",
                                    name=form["password"].name,
                                    maxlength="128",
                                    placeholder=str(tm("password")),
                                    required=True,
                                    class_="textinput textInput form-control",
                                ),
                                h.label(
                                    for_=form["password"].id_for_label,
                                )[form["password"].label],
                            ],
                            h.input(
                                type="hidden",
                                name="next",
                                value=next_url or "",
                            ),
                            h.div(".row")[
                                h.div(".col-auto")[
                                    h.input(
                                        ".btn.btn-primary.white",
                                        type="submit",
                                        value=str(tm("log_in")),
                                    ),
                                ],
                            ],
                        ],
                    ],
                ],
            ],
        ]
