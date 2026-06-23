from django.utils import formats, timezone

import htpy as h

from my_app.models import ScreeningResultStatus
from my_app.views.screening.util import BADGE_CLASSES
from shortcuts import tdt


def Badge(label, class_name, badge_id=None):
    attrs = {
        "class_": f"badge rounded-pill {class_name}",
    }
    if badge_id is not None:
        attrs["id"] = badge_id

    return h.span(**attrs)[label]


def NotStartedBadge():
    return Badge(
        ScreeningResultStatus.NOT_STARTED.label,
        BADGE_CLASSES[ScreeningResultStatus.NOT_STARTED],
    )


def EmptyCitationPageMessage():
    return h.p(".text-muted.mb-0")[tdt("No citations on this page.")]


def human_review_control_id(prefix, result):
    return f"{prefix}-human-review-{result.id}"


def render_ai_answer(result):
    if result.selected_option is None:
        return h.span(".text-muted")[tdt("No option selected")]

    return h.div[
        h.div(".fw-semibold")[result.selected_option.option_text],
        h.div(".small.text-muted")[result.selected_option.option_value],
    ]


def render_human_review_control(
    result,
    *,
    prefix,
    answer_url,
    validate_url,
    undo_validation_url,
):
    control_id = human_review_control_id(prefix, result)

    if result.human_selected_answer_id is not None:
        answer = result.human_selected_answer
        content = [
            h.div(".fw-semibold")[answer.option_text],
            h.div(".small.text-muted")[answer.option_value],
            (
                h.p(".small.mt-2.mb-0")[result.human_notes]
                if result.human_notes
                else None
            ),
            h.div(".d-flex.flex-wrap.align-items-center.gap-2.mt-2")[
                h.span(".badge.text-bg-info")[tdt("Human entered")],
                h.button(
                    ".btn.btn-outline-secondary.btn-sm",
                    type="button",
                    hx_get=answer_url,
                    hx_target="#modal-slot",
                    hx_swap="innerHTML",
                )[tdt("Edit")],
            ],
        ]
    elif result.human_validation_timestamp is not None:
        validator = result.human_validated_by
        validator_name = (
            validator.get_full_name() or validator.get_username()
            if validator is not None
            else tdt("Unknown user")
        )
        validation_timestamp = timezone.localtime(
            result.human_validation_timestamp
        )
        content = h.div(".vstack.gap-2")[
            render_ai_answer(result),
            h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
                h.span(".badge.text-bg-success")[tdt("Validated")],
                h.span(".small.text-muted")[
                    validator_name,
                    " - ",
                    h.time(datetime=validation_timestamp.isoformat())[
                        formats.date_format(
                            validation_timestamp,
                            "DATETIME_FORMAT",
                        )
                    ],
                ],
            ],
            h.div[
                h.button(
                    ".btn.btn-outline-secondary.btn-sm",
                    type="button",
                    hx_post=undo_validation_url,
                    hx_target=f"#{control_id}",
                    hx_swap="outerHTML",
                )[tdt("Undo")]
            ],
        ]
    else:
        content = h.div(".vstack.gap-2")[
            render_ai_answer(result),
            h.div(".d-flex.flex-wrap.gap-2")[
                h.button(
                    ".btn.btn-success.btn-sm",
                    type="button",
                    hx_post=validate_url,
                    hx_target=f"#{control_id}",
                    hx_swap="outerHTML",
                )[tdt("Validate correct")],
                h.button(
                    ".btn.btn-outline-primary.btn-sm",
                    type="button",
                    hx_get=answer_url,
                    hx_target="#modal-slot",
                    hx_swap="innerHTML",
                )[tdt("Manually answer screening")],
            ],
        ]

    return h.div(id=control_id)[content]
