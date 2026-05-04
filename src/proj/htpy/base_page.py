from django.conf import settings
from django.contrib.messages import get_messages
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse

import htpy as h
import phac_aspc.django.helpers.templatetags as phac_aspc
from data_fetcher.util import get_request
from django_htmx.templatetags.django_htmx import django_htmx_script
from markupsafe import Markup

from proj.jinja_helpers import (
    get_lang_code,
    get_other_lang,
    message_type,
    url_to_other_lang,
)
from proj.text import tdt, tm

from .util import HtpyComponent


def static_no_cache(path):
    if settings.DEBUG:
        return static(path)
    return static(path) + f"?v={settings.STATIC_BUST_TOKEN}"


def MessagesBar(request: HttpRequest):
    """
    Useful as a separate component
    in case a view wants to swap in messages via HTMX

    note that aria-live only announced new messages that are swapped in,
    not existing messages that are already in the DOM when the page loads
    """
    messages = getattr(request, "_messages", None)
    if not messages:

        messages = get_messages(request)

    message_list = list(messages) or []

    return h.div(
        id="message-bar",
        hx_swap_oob="beforeend",
        hx_swap="beforeend",
        tabindex="-1",
        style="position: sticky; top: 0; z-index: 998;",
        role="alert",
        aria_live="polite",
    )[
        [
            h.div(
                f".django-message.alert.alert-{message_type(msg)}.alert-dismissible.fade.show"
            )[
                h.div({"class": "container", "style": "position: relative;"})[
                    h.div[
                        Markup(str(msg)),
                        h.button(
                            type="button",
                            class_="btn-close",
                            data_bs_dismiss="alert",
                            aria_label="Close",
                            style="padding: 0.25em;",
                        ),
                    ]
                ]
            ]
            for msg in message_list
        ]
    ]


class BasePageTemplate(HtpyComponent):
    def __init__(self, context, request):
        super().__init__()
        self.context = context
        self.request = request

    def head_title(self):
        return tm("site_title")

    def head_medias(self):
        return None

    def head_extra_scripts_css(self):
        return None

    def head(self):
        debug = getattr(self.request, "debug", False) or getattr(
            self.request, "_request", None
        )
        # debug context processor sets debug based on DEBUG and INTERNAL_IPS
        from django.conf import settings

        is_debug = settings.DEBUG

        return h.head[
            h.title[self.head_title()],
            h.meta(
                content="width=device-width,initial-scale=1", name="viewport"
            ),
            h.link(
                rel="apple-touch-icon",
                sizes="57x57 72x72 114x114 144x144 150x150",
                class_="wb-favicon",
                href="https://www.canada.ca/etc/designs/canada/wet-boew/assets/favicon-mobile.png",
            ),
            h.link(
                href="https://www.canada.ca/etc/designs/canada/wet-boew/assets/favicon.ico",
                rel="icon",
                type="image/x-icon",
                class_="wb-init wb-favicon-inited",
            ),
            h.link(
                rel="stylesheet",
                href=static("third_party/css/bootstrap.min.css"),
            ),
            h.link(rel="stylesheet", href=static_no_cache("site.css")),
            h.script(src=static("third_party/js/jquery-3.7.1.min.js")),
            h.script(src=static("third_party/js/htmx.min.js")),
            h.script(src=static("third_party/js/idiomorph.min.js")),
            h.script(src=static("third_party/js/idiomorph-ext.min.js")),
            h.script(src=static("third_party/js/bootstrap.bundle.min.js")),
            Markup(django_htmx_script()) if is_debug else None,
            self.head_medias(),
            self.head_extra_scripts_css(),
        ]

    def nav_logo(self):
        lang = "en" if get_lang_code() == "en-ca" else "fr"
        return Markup(
            phac_aspc.phac_aspc_inline_svg(
                f"phac_aspc_helpers/phac_logos/{lang}__dark.svg",
                style="height: 2rem; padding-right: 2rem;",
            )
        )

    def available_apps(self):
        return None

    def header_menu(self):
        return None

    def nav_container(self):
        request = self.request
        user = request.user
        context = {"request": request}

        return h.nav(".navbar.navbar-expand-md.navbar-dark.bg-dark")[
            h.div(".container")[
                self.nav_logo(),
                self.available_apps(),
                h.button(
                    ".navbar-toggler",
                    type="button",
                    data_bs_toggle="collapse",
                    data_bs_target="#navbarSupportedContent",
                    aria_controls="navbarSupportedContent",
                    aria_expanded="false",
                    aria_label="Toggle navigation",
                )[h.span(".navbar-toggler-icon")],
                h.div(
                    ".collapse.navbar-collapse", id="navbarSupportedContent"
                )[
                    self.header_menu(),
                    h.ul(".navbar-nav.flex-fill.justify-content-end")[
                        h.li(".nav-item")[
                            h.a(
                                ".nav-link.text-white",
                                href=url_to_other_lang(context),
                            )[get_other_lang()],
                        ],
                        (
                            h.li(".nav-item.dropdown")[
                                h.a(
                                    ".nav-link.dropdown-toggle.text-white",
                                    href="#",
                                    id="navbarDropdown",
                                    role="button",
                                    data_bs_toggle="dropdown",
                                    aria_haspopup="true",
                                    aria_expanded="false",
                                )[str(user)],
                                h.div(
                                    ".dropdown-menu",
                                    aria_labelledby="navbarDropdown",
                                )[get_top_right_dropdown_items(request)],
                            ]
                            if user.is_authenticated
                            else None
                        ),
                    ],
                ],
            ],
        ]

    def csrf_script(self):

        csrf_token = get_token(self.request)
        return Markup(
            f"""<script>
      document.body.addEventListener('htmx:configRequest', (event) => {{
        event.detail.headers['X-CSRFToken'] = '{csrf_token}';
      }})
    </script>"""
        )

    def messages(self):
        return MessagesBar(self.request)

    def content(self):
        return None

    def content_fluid(self):
        return None

    def footer(self):
        return h.footer(".d-print-none.goc-footer.bg-light")[
            h.div(".container")[
                h.div(".row")[
                    h.div(".col"),
                    h.div(".col-auto")[
                        h.object_(
                            type="image/svg+xml",
                            tabindex="-1",
                            role="img",
                            data=static("third_party/img/wmms-blk.svg"),
                            aria_label="Symbol of the Government of Canada",
                            style="height: 2rem; margin: 1rem 0;",
                        ),
                    ],
                ],
            ],
        ]

    def render(self):
        return h.html(lang="en")[
            self.head(),
            h.body(hx_ext="morph")[
                h.div(".d-none")[h.div(id="dummy-target")],
                h.div(id="modal-slot", data_modal_slot=True),
                h.script(
                    src=static_no_cache("phac_aspc_helpers/modal/modal.js")
                ),
                h.link(
                    rel="stylesheet",
                    href=static_no_cache("phac_aspc_helpers/modal/modal.css"),
                ),
                h.script(src=static_no_cache("site.js")),
                self.csrf_script(),
                self.nav_container(),
                h.main(".pt-3.pb-5", style="min-height: 85vh")[
                    self.messages(),
                    h.div[
                        h.div("#content.container")[self.content()],
                        h.div("#content-fluid.container-fluid.p-0")[
                            h.div(".ms-5.me-5")[self.content_fluid()],
                        ],
                    ],
                ],
                self.footer(),
                phac_aspc.phac_aspc_wet_scripts(include_jquery=False),
            ],
        ]


class BasePageComponent(BasePageTemplate):
    """
    If you'd prefer tighter coupling with the view,
    you may set content, title and content_fluid via context
    and use this component as a template
    """

    def title(self):
        return self.context.get("title") or super().head_title()

    def content(self):
        return self.context.get("content") or super().content()

    def content_fluid(self):
        return self.context.get("content_fluid") or super().content_fluid()


def get_top_right_dropdown_items(request):
    return [
        h.a(
            ".dropdown-item",
            href=reverse("logout"),
        )[
            h.i(".fa.fa-power-off"),
            tm("logout"),
        ],
        h.a(
            ".dropdown-item",
            href=reverse("llm_demo"),
        )[tdt("LLM demo")],
        h.a(
            ".dropdown-item",
            href=reverse("document_list"),
        )[tm("documents")],
        h.a(
            ".dropdown-item",
            href=reverse("systematic_review_list"),
        )[tdt("Systematic reviews")],
    ]
