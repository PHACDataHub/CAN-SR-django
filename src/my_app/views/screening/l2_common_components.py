from dataclasses import dataclass

from django.utils import formats, timezone

import htpy as h

from proj.htpy.form_components import ErrorSummary
from proj.htpy.modal_component import ModalComponent

from my_app.models import (
    Citation,
    Document,
    L2ScreeningResult,
    Review,
    TextExtractionResult,
)
from my_app.views.screening.components import Badge
from my_app.views.screening.util import BADGE_CLASSES
from shortcuts import GenericForm, reverse, tdt


def DocumentUploadBadge(citation_row: Citation):
    if citation_row.document is None:
        return Badge(
            tdt("Not uploaded"),
            BADGE_CLASSES["missing"],
        )

    return Badge(
        tdt("Uploaded"),
        BADGE_CLASSES["uploaded"],
    )


def TextExtractionBadge(citation_row: Citation):
    document = citation_row.document
    if document is None:
        return None

    text_extraction_result = getattr(document, "text_extraction_result", None)
    if text_extraction_result is None:
        status = TextExtractionResult.TextExtractionStatus.NOT_STARTED
    else:
        status = text_extraction_result.status

    return Badge(
        TextExtractionResult.TextExtractionStatus(status).label,
        BADGE_CLASSES[status],
    )


def FigureExtractionBadge(citation_row: Citation):
    document = citation_row.document
    if document is None:
        return None

    figure_extraction_result = getattr(
        document, "figure_extraction_result", None
    )
    if figure_extraction_result is None:
        status = TextExtractionResult.TextExtractionStatus.NOT_STARTED
    else:
        status = figure_extraction_result.status

    return Badge(
        TextExtractionResult.TextExtractionStatus(status).label,
        BADGE_CLASSES[status],
    )


def L2ScreeningBadge(citation_row: Citation, status_fetcher):
    status = status_fetcher.get(citation_row.id)
    return Badge(
        status.label,
        BADGE_CLASSES[status],
        badge_id=f"l2-screening-row-status-{citation_row.id}",
    )


def get_l2_pdf_detail_url(review: Review, citation_row: Citation):
    return reverse("screen_l2_row_details", args=[review.id, citation_row.id])


def get_l2_pdf_upload_url(review: Review, citation_row: Citation):
    return reverse("screen_l2_row_upload", args=[review.id, citation_row.id])


def render_l2_pdf_modal_button(
    citation_row: Citation,
    review: Review,
):
    return h.button(
        ".btn.btn-outline-primary.btn-sm",
        type="button",
        hx_get=get_l2_pdf_upload_url(review, citation_row),
        hx_target="#modal-slot",
        hx_swap="innerHTML",
    )[tdt("Re-upload") if citation_row.document is not None else tdt("Upload")]


def render_l2_pdf_detail_link(citation_row: Citation, review: Review):
    return h.a(
        ".btn.btn-outline-secondary.btn-sm",
        href=get_l2_pdf_detail_url(review, citation_row),
    )[tdt("View")]


def l2_human_review_control_id(result):
    return f"l2-human-review-{result.id}"


def render_l2_ai_answer(result: L2ScreeningResult):
    if result.selected_option is None:
        return h.span(".text-muted")[tdt("No option selected")]

    return h.div[
        h.div(".fw-semibold")[result.selected_option.option_text],
        h.div(".small.text-muted")[result.selected_option.option_value],
    ]


def render_l2_human_review_control(result: L2ScreeningResult, review: Review):
    control_id = l2_human_review_control_id(result)
    answer_url = reverse("screen_l2_human_answer", args=[review.id, result.id])

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
            render_l2_ai_answer(result),
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
                    hx_post=reverse(
                        "screen_l2_undo_validation",
                        args=[review.id, result.id],
                    ),
                    hx_target=f"#{control_id}",
                    hx_swap="outerHTML",
                )[tdt("Undo")]
            ],
        ]
    else:
        content = h.div(".vstack.gap-2")[
            render_l2_ai_answer(result),
            h.div(".d-flex.flex-wrap.gap-2")[
                h.button(
                    ".btn.btn-success.btn-sm",
                    type="button",
                    hx_post=reverse(
                        "screen_l2_validate_correct",
                        args=[review.id, result.id],
                    ),
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


@dataclass
class L2DocumentUploadModal:
    form: object
    review: Review
    citation_row: Citation
    existing_document: Document | None

    @property
    def modal_id(self):
        return f"l2-screening-upload-modal-{self.citation_row.id}"

    @property
    def form_id(self):
        return f"l2-screening-upload-form-{self.citation_row.id}"

    def render(self):
        title = (
            tdt("Replace document")
            if self.existing_document is not None
            else tdt("Upload document")
        )

        footer = h.fragment[
            h.button(
                {
                    "type": "button",
                    "class": "btn btn-secondary",
                    "data-modal-close": True,
                }
            )[tdt("Cancel")],
        ]

        return ModalComponent(
            title=title,
            modal_id=self.modal_id,
            footer=footer,
        )[self.render_form_body()]

    def render_form_body(self):
        return h.form(
            id=self.form_id,
            method="post",
            enctype="multipart/form-data",
            novalidate=True,
            hx_post=reverse(
                "screen_l2_row_upload",
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target="#modal-slot",
            hx_swap="innerHTML",
            hx_encoding="multipart/form-data",
        )[
            ErrorSummary([self.form]),
            GenericForm(self.form),
            h.div(".mt-3.text-end")[
                h.button(
                    ".btn.btn-primary",
                    type="submit",
                    **{"hx-disabled-elt": "this"},
                )[
                    (
                        tdt("Replace document")
                        if self.existing_document is not None
                        else tdt("Upload document")
                    )
                ]
            ],
        ]
