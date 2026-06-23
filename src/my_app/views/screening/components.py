from django.utils import formats, timezone

import htpy as h

from my_app.models import ScreeningResultStatus
from my_app.queries import get_adjacent_citation_ids
from my_app.views.screening.util import BADGE_CLASSES
from shortcuts import reverse, tdt


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


def CitationScreeningProgressNav(
    citation_row,
    review,
    *,
    detail_route_name,
    progress_stats,
    nav_label,
):
    previous_id, next_id = get_adjacent_citation_ids(citation_row.id)
    progress_title = (
        f"{tdt('Total citations')}: {progress_stats.total_citations}; "
        f"{tdt('Incomplete')}: {progress_stats.incomplete_citations}; "
        f"{tdt('Complete, awaiting human review')}: "
        f"{progress_stats.completed_not_human_reviewed_citations}; "
        f"{tdt('Human reviewed')}: {progress_stats.human_reviewed_citations}"
    )
    position_label = (
        f"{tdt('Viewing')} {citation_row.order} {tdt('of')} "
        f"{progress_stats.total_citations}"
    )

    return h.section(".border.rounded.p-3.mb-4")[
        h.div(".row.g-3.align-items-center")[
            h.div(".col-md-4")[
                h.div(".d-flex.flex-wrap.align-items-center.gap-3")[
                    h.div(
                        ".btn-group",
                        role="group",
                        aria_label=nav_label,
                    )[
                        _citation_nav_button(
                            previous_id,
                            review,
                            detail_route_name,
                            tdt("Previous"),
                        ),
                        _citation_nav_button(
                            next_id,
                            review,
                            detail_route_name,
                            tdt("Next"),
                        ),
                    ],
                    h.div(".small.text-muted")[position_label],
                ]
            ],
            h.div(".col-md-8")[
                h.div(
                    ".d-flex.justify-content-between.align-items-center.mb-2"
                )[
                    h.span(".small.text-muted")[tdt("Human reviewed")],
                    h.span(".small.fw-semibold", title=progress_title)[
                        str(progress_stats.human_reviewed_citations),
                        " / ",
                        str(progress_stats.total_citations),
                    ],
                ],
                h.div(
                    ".progress",
                    role="progressbar",
                    aria_label=progress_title,
                    aria_valuenow=str(progress_stats.human_reviewed_percent),
                    aria_valuemin="0",
                    aria_valuemax="100",
                    title=progress_title,
                )[
                    h.div(
                        ".progress-bar",
                        style=(
                            f"width: {progress_stats.human_reviewed_percent}%"
                        ),
                    )[f"{progress_stats.human_reviewed_percent}%"],
                ],
            ],
        ]
    ]


def _citation_nav_button(citation_id, review, detail_route_name, label):
    if citation_id is None:
        return h.a(
            ".btn.btn-outline-primary.disabled",
            href="#",
            aria_disabled="true",
            tabindex="-1",
        )[label]

    return h.a(
        ".btn.btn-outline-primary",
        href=reverse(detail_route_name, args=[review.id, citation_id]),
    )[label]


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
