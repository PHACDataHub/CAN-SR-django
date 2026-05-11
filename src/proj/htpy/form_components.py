from typing import Callable

from django import forms
from django.conf import settings

import htpy
from htpy import Node, Renderable
from markupsafe import Markup
from phac_aspc.vanilla import flatten

from proj.htpy.context_providers import (
    WithAriaLabelledBy,
    aria_labelledby_context,
)
from proj.text import tdt, tm

from .util import as_safe_renderable


def InlineFormset(
    formset,
    form_renderer: Callable[[forms.Form], Node],
    add_button_text: Node = None,
    can_add: bool = False,
    aria_list_label: str | None = None,
) -> Node:
    """
    Inline formset layout with dynamic add functionality.

    Args:
        formset: Django formset instance
        form_renderer: Callable that renders a single form
        add_button_text: Text for the add button (defaults to translated "add")
        can_add: Whether to show the add button
        can_add will be ignored if the formset has editable=False
        aria_list_label: Optional label for the list of forms, adds label
            and indices to each form's subtree of fields' aria-labeledby
    """

    formset_prefix = formset.prefix
    formset_template_id = f"formset-template-{formset_prefix}"
    formset_container_id = f"formset-container-{formset_prefix}"
    add_button_id = f"add-{formset_prefix}"

    forms = [form for form in formset]

    if aria_list_label:
        """
        This is complex

        The formset root contains a hidden container with a few ID'd spans
        one span corresponds to the formset as a whole, e.g. "Contacts"
        each form also gets an ID span, "Entry 1", "Entry 2", etc,
        all form inputs in the entire formset will refer
            to the root span, and their own form's index span,
            aria-labelledby="{{formset_prefix}}-aria-list {{formset_prefix}}-aria-list-item-1"

            This is 'magically' done via htpy context,
                provided by WithAriaLabelledBy

        In addition, because forms can be added dynamically,
            we also need a template span
            so that new {{formset_prefix}}-aria-list-item-<INDEX>
            can be added as new forms get added
            See dynamic_formsets.js for more

        """

        formset_root_aria_label_id = f"{formset_prefix}-aria-list"

        def label_id_for_index(i: int | str) -> str:
            return f"{formset_root_aria_label_id}-item-{i}"

        label_section_id = f"{formset_prefix}-aria-labels-container"
        label_section = htpy.div({"class": "d-none", "id": label_section_id})[
            htpy.span({"id": formset_root_aria_label_id})[aria_list_label],
            htpy.span(
                {
                    "id": label_id_for_index("REPLACE_ME_WITH_INDEX"),
                    "class": "form-index-label form-index-label-template",
                }
            )[tm("entry"), htpy.span(".entry-index")["999"]],
            (
                htpy.span(
                    {"id": label_id_for_index(i), "class": "form-index-label"}
                )[tm("entry"), htpy.span(".entry-index")[i + 1]]
                for i, form in enumerate(forms)
            ),
        ]
        form_items = WithAriaLabelledBy(label_id=formset_root_aria_label_id)[
            (
                WithAriaLabelledBy(label_id=label_id_for_index(i))[
                    form_renderer(form)
                ]
                for i, form in enumerate(forms)
            )
        ]

        form_template = WithAriaLabelledBy(
            label_id=formset_root_aria_label_id
        )[
            WithAriaLabelledBy(
                label_id=label_id_for_index("REPLACE_ME_WITH_INDEX")
            )[form_renderer(formset.empty_form)]
        ]

    else:
        label_section = None
        form_items = [form_renderer(form) for form in forms]
        form_template = form_renderer(formset.empty_form)

    # Add button
    add_button = None
    if can_add:
        button_text = add_button_text if add_button_text else _("add")
        add_button = htpy.div(".text-center.my-2")[
            htpy.button(
                {
                    "type": "button",
                    "class": "btn btn-secondary",
                    "id": add_button_id,
                }
            )[as_safe_renderable(button_text)]
        ]

    # JavaScript for dynamic formset
    if can_add:
        script = htpy.script[
            Markup(
                f"""
        new DynamicFormsetManager({{
        formsetPrefix: "{formset_prefix}",
        formListSelector: "#{formset_container_id}",
        templateContainerSelector: "#{formset_template_id}",
        addButtonSelector: "#{add_button_id}",
        }}).activate();
        """
            )
        ]
    else:
        script = None

    debug_section = None
    if settings.FEATURE_FLAG:
        if aria_list_label:
            debug_section = htpy.div(".alert.alert-info.p-2.m-0")[
                "formset aria_list_label: ",
                aria_list_label,
            ]
        else:
            debug_section = htpy.div(".alert.alert-warning")[
                "Missing aria_list_label"
            ]

    return htpy.div(
        {
            "class": f"formset-root formset-root-{formset_prefix} border rounded-2 p-3 m-2"
        }
    )[
        # Hidden template for new items
        label_section,
        htpy.fragment[debug_section],
        htpy.div({"class": "d-none", "id": formset_template_id})[
            form_template
        ],
        # Management form
        Markup(str(formset.management_form)),
        # Form container
        htpy.div({"id": formset_container_id})[form_items],
        add_button,
        script,
    ]


def ErrorSummary(form_list: list[forms.Form]) -> Node:

    has_errors = False
    for form in form_list:
        for field in form.visible_fields():
            if field.errors:
                has_errors = True
                break

        if has_errors:
            break

    if not has_errors:
        return None

    all_fields = flatten([form.visible_fields() for form in form_list])

    return htpy.div(
        {
            "id": "form-error-summary",
            "class": "alert alert-danger",
            "tabindex": "0",
            "role": "alert",
            "autofocus": "true",
        }
    )[
        htpy.h2({"class": "h4"})[tm("form_not_saved")],
        htpy.ul[
            (
                htpy.li[
                    htpy.a({"href": f"#{field.id_for_label}"})[
                        htpy.strong[field.label],
                        htpy.span[" - "],
                        htpy.span[", ".join(field.errors)],
                    ]
                ]
                for field in all_fields
                if field.errors
            )
        ],
    ]
