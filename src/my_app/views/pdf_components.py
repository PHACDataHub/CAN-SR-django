from dataclasses import dataclass

import htpy as h

from proj.htpy.form_components import ErrorSummary
from proj.htpy.modal_component import ModalComponent
from proj.htpy.util import static_no_cache

from my_app.models import (
    Citation,
    Document,
    FigureExtractionResult,
    Review,
    ScreeningResultStatus,
    TextExtractionResult,
)
from shortcuts import GenericForm, reverse, tdt

BADGE_CLASSES = {
    # warning: redundant keys are intentionally here
    # this is ok until they map to different badges, but that's unlikely
    ScreeningResultStatus.NOT_STARTED: "bg-secondary",
    ScreeningResultStatus.PENDING: "bg-warning text-dark",
    ScreeningResultStatus.COMPLETED: "bg-success",
    ScreeningResultStatus.ABANDONED: "bg-danger",
    "uploaded": "bg-success",
    "missing": "bg-secondary",
    TextExtractionResult.TextExtractionStatus.NOT_STARTED: "bg-secondary",
    TextExtractionResult.TextExtractionStatus.PENDING: "bg-warning text-dark",
    TextExtractionResult.TextExtractionStatus.COMPLETED: "bg-success",
    TextExtractionResult.TextExtractionStatus.FAILED: "bg-danger",
    FigureExtractionResult.Status.NOT_STARTED: "bg-secondary",
    FigureExtractionResult.Status.PENDING: "bg-warning text-dark",
    FigureExtractionResult.Status.COMPLETED: "bg-success",
    FigureExtractionResult.Status.FAILED: "bg-danger",
}


def Badge(label, class_name, badge_id=None):
    attrs = {
        "class_": f"badge rounded-pill {class_name}",
    }
    if badge_id is not None:
        attrs["id"] = badge_id

    return h.span(**attrs)[label]


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


def render_pdf_detail_link(citation_row: Citation, review: Review, route_name):
    return h.a(
        ".btn.btn-outline-secondary.btn-sm",
        href=reverse(route_name, args=[review.id, citation_row.id]),
    )[tdt("View")]


def render_pdf_modal_button(
    citation_row: Citation,
    review: Review,
    route_name,
):
    return h.button(
        ".btn.btn-outline-primary.btn-sm",
        type="button",
        hx_get=reverse(route_name, args=[review.id, citation_row.id]),
        hx_target="#modal-slot",
        hx_swap="innerHTML",
    )[tdt("Re-upload") if citation_row.document is not None else tdt("Upload")]


@dataclass
class DocumentUploadModal:
    form: object
    review: Review
    citation_row: Citation
    existing_document: Document | None
    route_name: str
    prefix: str

    @property
    def modal_id(self):
        return f"{self.prefix}-upload-modal-{self.citation_row.id}"

    @property
    def form_id(self):
        return f"{self.prefix}-upload-form-{self.citation_row.id}"

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
                self.route_name,
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


def PdfViewerAssets(
    citation_row: Citation,
    review: Review,
    data_id: str,
    pdf_route_name: str,
    metadata_route_name: str,
):
    pdf_url = None
    metadata_url = None
    if citation_row.document_id is not None:
        pdf_url = reverse(pdf_route_name, args=[review.id, citation_row.id])
        metadata_url = reverse(
            metadata_route_name,
            args=[review.id, citation_row.id],
        )

    return h.fragment[
        h.template(
            id=data_id,
            data_citation_id=str(citation_row.id),
            data_review_id=str(review.id),
            data_pdf_url=pdf_url,
            data_metadata_url=metadata_url,
        ),
        h.script(
            src=static_no_cache("citation_pdf.js"),
            type="module",
        ),
        h.link(
            rel="stylesheet",
            href=static_no_cache("citation_pdf.css"),
        ),
    ]


def PdfPanel(citation_row: Citation):
    if citation_row.document_id is None:
        initial_status = tdt("Upload a PDF to view the document.")
    else:
        initial_status = tdt("Loading PDF...")

    return h.section(
        ".citation-pdf-panel",
        aria_label=tdt("Citation PDF viewer"),
    )[
        h.div(".citation-pdf-toolbar")[
            h.h2(".h5.mb-0")[tdt("Document")],
            h.span(
                ".small.text-muted",
                id="citation-pdf-status",
                role="status",
                aria_live="polite",
            )[initial_status],
        ],
        h.div(
            ".citation-pdf-scroll",
            id="citation-pdf-scroll",
            tabindex="0",
        )[
            h.div(".citation-pdf-pages", id="citation-pdf-pages"),
        ],
    ]


def render_evidence_chips(
    evidence_indices,
    evidence_type,
    label,
    aria_label,
):
    if not evidence_indices:
        return tdt("Nothing to highlight")

    evidence_list = ", ".join(
        str(evidence_index) for evidence_index in evidence_indices
    )
    return h.div(
        ".d-flex.flex-wrap.gap-2",
        aria_label=f"{aria_label}: {evidence_list}",
    )[
        [
            h.button(
                ".btn.btn-sm.btn-outline-primary.evidence-chip",
                type="button",
                data_evidence_type=evidence_type,
                data_evidence_index=str(evidence_index),
            )[label, " ", str(evidence_index)]
            for evidence_index in evidence_indices
        ]
    ]
