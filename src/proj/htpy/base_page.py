import json
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.contrib.messages import get_messages
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import get_language

import htpy as h
import phac_aspc.django.helpers.templatetags as phac_aspc
from data_fetcher.util import get_request
from django_htmx.templatetags.django_htmx import django_htmx_script
from markupsafe import Markup
from phac_aspc.rules import test_rule

from proj.text import tdt, tm

from .util import HtpyComponent, static_no_cache


def get_lang_code():
    """
    Provides the language code for the current language
    """
    current_lang = get_language()
    return current_lang.lower()


def get_other_lang():
    """
    Returns the language not currently being used (Ex. if current lang
    is en, then the other lang is French.  This is used as the label for the
    button to switch languages)
    """
    current_lang = get_language()
    if "en" in current_lang.lower():
        return "Français"
    return "English"


def message_type(message):
    # remaps the message level tag to the bootstrap alert type
    if message.level_tag == "error":
        return "danger"
    else:
        return f"{message.level_tag}"


def convert_url_other_lang(url_str):
    parsed_url = urlparse(url_str)
    path = parsed_url.path
    query = parsed_url.query

    if "fr-ca" in path:
        new_path = path.replace("/fr-ca", "")
    else:
        new_path = "/fr-ca" + path

    new_url = parsed_url._replace(path=new_path)

    if "login" in path and "next" in query:
        if "fr-ca" in path:
            new_query = query.replace("next=/fr-ca", "next=")
        else:
            new_query = query.replace("next=", "next=/fr-ca")
    else:
        new_query = query

    new_url = new_url._replace(query=new_query)

    return urlunparse(new_url)


def url_to_other_lang():
    """
    Provides the URL to the other language:
    For example, if current language is English then it will provide
    the url to the French language.
    """
    request = get_request()
    full_uri = request.get_full_path()
    return convert_url_other_lang(full_uri)


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
            h.script(src=static("dynamic_formsets.js")),
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
                                href=url_to_other_lang(),
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
                h.script(
                    src=static_no_cache("site.js"),
                    data_csrf_token=get_token(self.request),
                    data_debug=json.dumps(settings.DEBUG),
                    data_feature_flag=json.dumps(settings.FEATURE_FLAG),
                ),
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
            href=reverse("review_list"),
        )[tdt("Systematic reviews")],
        h.a(
            ".dropdown-item",
            href=reverse("background_tasks_demo"),
        )[tdt("Background tasks demo")],
        test_rule("is_admin", request.user)
        and h.a(
            ".dropdown-item",
            href=reverse("admin:index"),
        )[tdt("django-admin")],
    ]
