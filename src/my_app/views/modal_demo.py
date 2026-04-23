from django import forms
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.views.generic import TemplateView, View

import htpy as h

from proj.htpy.base_page import MessagesBar
from proj.htpy.generic_form import GenericForm
from proj.htpy.modal_base import ModalComponent
from proj.htpy.util import HtpyTemplatelessMixin
from proj.text import tdt

from my_app.router import route

# ── Form ──


class DemoForm(forms.Form):
    name = forms.CharField(max_length=100, label="Name")
    email = forms.EmailField(label="Email")


# ── Modal components ──


def StaticModal():
    return ModalComponent(
        title=tdt("Static modal"),
        modal_id="static-modal",
    )[
        h.p[tdt("static_modal_body")],
        h.h5[tdt("Nested modals")],
        h.p[tdt("nested_modal_description")],
        # Opens a second modal on top of this one.
        # The nested modal can live anywhere in the DOM.
        h.button(
            ".btn.btn-outline-primary",
            data_modal_open="nested-modal",
        )[tdt("Open nested modal")],
    ]


def NestedModal():
    """
    Opened from inside another modal. Stacks on top with its own
    backdrop. Escape / close only dismisses this one.
    Placed separately in the DOM to show modals don't need to be
    nested in markup — only in the visual stack.
    """
    return ModalComponent(
        title=tdt("Nested modal"),
        modal_id="nested-modal",
    )[h.p[tdt("nested_modal_body")]]


def ProgrammaticModal():
    return ModalComponent(
        size_cls="modal-xl",
        title="Programmatic JS modal",
        modal_id="programmatic-modal",
    )[
        h.p[
            "This modal is opened with JavaScript instead of a data-modal-open attribute."
        ],
        h.pre(".bg-light.border.rounded.p-3")[
            h.code[
                'window.ModalStack.open(document.getElementById("programmatic-modal"))'
            ]
        ],
        h.p(".mt-3")[
            "This button closes the modal by calling the modal JS API directly."
        ],
        h.pre(".bg-light.border.rounded.p-3")[
            h.code[
                'window.ModalStack.close(document.getElementById("programmatic-modal"))'
            ]
        ],
        h.button(
            ".btn.btn-outline-primary",
            type="button",
            onclick='window.ModalStack.close(document.getElementById("programmatic-modal"))',
        )["Close modal via JS"],
        h.button(
            ".btn.btn-outline-primary",
            type="button",
            onclick='window.ModalStack.close(document.getElementById("programmatic-modal"),false)',
        )["Close modal via JS w/out resetting focus"],
    ]


def NonClosingModal():
    """
    Demonstrates the option to prevent closing on outside click by adding
    data-modal-close-on-outside-click="false" to the modal wrapper.
    """
    return ModalComponent(
        title="Non-closing modal",
        modal_id="non-closing-modal",
        close_on_outside_click=False,
    )[
        h.p[
            "this modal will not close when clicking outside, but will close with the buttons or escape key"
        ]
    ]


def HtmxModal():
    """
    Fetched from the server via HTMX, swapped into #modal-slot.
    The JS auto-opens any [data-modal] that appears inside
    a [data-modal-slot] after an htmx:afterSettle event.

    Also demonstrates nesting from within an HTMX-loaded modal:
    the nested modal markup is included in the response body.
    """

    return ModalComponent(
        title=tdt("HTMX modal"),
        modal_id="htmx-modal",
        size_cls="modal-lg",
    )[
        h.p[tdt("htmx_modal_body")],
        h.p[tdt("nested_from_htmx_description")],
        h.button(
            ".btn.btn-outline-primary",
            data_modal_open="nested-from-htmx",
        )[tdt("Open nested modal")],
        # Nested modal rendered inline in the HTMX response.
        # Works the same as a static nested modal.
        ModalComponent(
            title=tdt("Nested modal"),
            modal_id="nested-from-htmx",
        )[h.p[tdt("nested_from_htmx_body")]],
    ]


# ── Views ──


@route("modal-demo/", name="modal_demo")
class ModalDemo(TemplateView, HtpyTemplatelessMixin):
    def title(self):
        return tdt("Modal demo")

    def content(self):
        return [
            h.h1[tdt("Modal demo")],
            h.p(".text-muted")[tdt("modal_demo_description")],
            h.hr,
            # ── 1. Static modal ──
            h.h2[tdt("Static modal")],
            h.p[tdt("static_modal_description")],
            h.button(
                ".btn.btn-primary",
                data_modal_open="static-modal",
            )[tdt("Open static modal")],
            StaticModal(),
            NestedModal(),
            h.hr,
            h.h2["Programmatic JS modal"],
            h.p["Open this static modal by calling JavaScript directly."],
            h.button(
                ".btn.btn-dark",
                type="button",
                onclick='window.ModalStack.open(document.getElementById("programmatic-modal"))',
            )["Open static modal via JS"],
            ProgrammaticModal(),
            h.hr,
            # ── 2. HTMX-swapped modal ──
            h.h2[tdt("HTMX modal")],
            h.p[tdt("htmx_modal_description")],
            # hx_target="#modal-slot" + hx_swap="innerHTML" is the
            # standard pattern for loading a modal via HTMX.
            # The response is a ModalComponent fragment; the JS auto-opens it.
            h.button(
                ".btn.btn-success",
                hx_get=reverse("modal_demo_htmx"),
                hx_target="#modal-slot",
                hx_swap="innerHTML",
            )[tdt("Load modal via HTMX")],
            h.hr,
            # ── 3. Form modal (single-route pattern) ──
            h.h2[tdt("Form modal")],
            h.p[tdt("form_modal_description")],
            # Same hx_target/hx_swap pattern. The ModalFormView handles
            # both GET (render modal) and POST (validate / close-or-rerender).
            h.button(
                ".btn.btn-info",
                hx_get=reverse("modal_demo_form"),
                hx_target="#modal-slot",
                hx_swap="innerHTML",
            )[tdt("Open form modal")],
            h.h2(".mt-4")["Modal spawned from dissapearing dropdown"],
            h.p[
                "since the triggering element dissapears, focus should return to the dropdown toggle"
            ],
            h.div[
                h.button(
                    ".btn.btn-outline-dark.dropdown-toggle",
                    type="button",
                    id="dropdown-demo-toggle",
                    data_bs_toggle="dropdown",
                )[tdt("Dropdown")],
                h.ul(".dropdown-menu")[
                    h.li[
                        h.button(
                            ".dropdown-item",
                            hx_get=reverse("modal_demo_htmx"),
                            hx_target="#modal-slot",
                            hx_swap="innerHTML",
                            data_focus_back="#random-button",
                        )[tdt("Open HTMX modal - focus back on diff button")],
                    ],
                    h.li[
                        h.button(
                            ".dropdown-item",
                            hx_get=reverse("modal_demo_htmx"),
                            hx_target="#modal-slot",
                            hx_swap="innerHTML",
                        )[tdt("open modal - default focus-back on ancestor")],
                    ],
                ],
            ],
            h.button("#random-button.btn.btn-primary.my-4")[
                tdt("Random button to test focus")
            ],
            h.div[
                h.button(
                    ".btn.btn-secondary", data_modal_open="non-closing-modal"
                )[tdt("Open non-closing modal")],
                NonClosingModal(),
            ],
            h.h2["Alternative slot"],
            h.div[
                h.div(
                    {"data-modal-slot": True, "id": "alternative-modal-slot"}
                ),
                h.button(
                    ".btn.btn-warning",
                    hx_get=reverse("modal_demo_htmx"),
                    hx_target="#alternative-modal-slot",
                    hx_swap="innerHTML",
                )[tdt("Load modal into alternative slot")],
            ],
        ]


@route("modal-demo/htmx-modal/", name="modal_demo_htmx")
class HtmxModalView(TemplateView, HtpyTemplatelessMixin):
    # Quick way to serve a modal fragment: override get() to bypass
    # the full page template and return just the modal HTML.
    def get(self, request, *args, **kwargs):
        return HttpResponse(str(HtmxModal()))


class ModalFormView(View):
    """

    This is an example form-in-a-modal-pattern

    Must override
      form_class     - a Django Form or ModelForm class
      modal_title    - string or htpy node for the modal header

    optional overrides
      modal_size     - e.g. "modal-lg", "modal-xl"
      close_on_success - if True (default), sends HX-Trigger: modal-close
                         on valid submission. Set False to handle manually.
      form_valid()   - hook for side effects on success, return an
                       HttpResponse to override the default 204.

    The trigger button should look like:
      hx-get=reverse("my_form_modal")
      hx-target="#modal-slot"
      hx-swap="innerHTML"

    How it works:
      GET  -> renders the full modal into the slot, auto-opens
             The form inside has hx-post pointing back to this same URL,
             targeting .modal-body (the modal's body div) so swaps stay
             inside the open modal
      POST (valid) -> calls form_valid(), returns 204 + HX-Trigger: modal-close
      POST (invalid) -> re-renders just the modal body (form with errors),
                        the modal stays open because only #modal-body is swapped.
    """

    form_class = None
    modal_title = ""
    modal_size = ""
    close_on_success = True

    def get_form(self, data=None):
        return self.form_class(data)

    def render_form(self, form):

        return h.form(
            method="post",
            hx_post=self.request.path,
            hx_target="closest .modal-body",
            hx_swap="innerHTML",
            novalidate=True,
        )[
            GenericForm(form, get_token(self.request)).render(),
            h.div(".text-end.mt-3")[
                h.button(".btn.btn-primary", type="submit")[tdt("save")],
            ],
        ]

    def get(self, request):
        form = self.get_form()

        node = ModalComponent(
            title=self.modal_title,
            size_cls=self.modal_size,
        )[
            self.render_form(form),
        ]

        return HttpResponse(str(node))

    def post(self, request):
        form = self.get_form(request.POST)
        if form.is_valid():
            custom = self.form_valid(form)
            if custom is not None:
                print("custom response from form_valid")
                return custom
            if self.close_on_success:
                resp = HttpResponse(status=204)
                resp["HX-Trigger"] = "modal-close"
                return resp

        # re-render just the body content; the modal stays open
        return HttpResponse(str(self.render_form(form)))

    def form_valid(self, form):

        return None


@route("modal-demo/form/", name="modal_demo_form")
class FormDemoModal(ModalFormView):
    """
    example usage of ModalFormView

    """

    form_class = DemoForm
    modal_title = tdt("Form modal")

    def form_valid(self, form):
        # renders a message that's immediately swapped into the page
        # comment this method out to see default behavior: 204 + close-modal
        from django.contrib import messages

        messages.success(self.request, tdt("form submitted successfully"))

        content = h.fragment[MessagesBar(self.request)]

        resp = HttpResponse(status=200, content=str(content))
        resp["HX-Trigger-After-Settle"] = "modal-close"
        resp["HX-Reswap"] = "none"

        return resp
