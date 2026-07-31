from dataclasses import dataclass

from django.utils.text import Truncator

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


def NotStartedBadge():
    return Badge(
        ScreeningResultStatus.NOT_STARTED.label,
        BADGE_CLASSES[ScreeningResultStatus.NOT_STARTED],
    )


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
):
    if citation_row.document is None:
        btn_text = tdt("Upload")
    else:
        btn_text = tdt("Re-upload")
    return h.button(
        ".btn.btn-outline-primary.btn-sm",
        id=f"upload-btn-{citation_row.id}",
        type="button",
        hx_get=reverse(
            "citation_upload_pdf_document_modal",
            args=[review.id, citation_row.id],
        ),
        hx_target="#modal-slot",
        hx_swap="innerHTML",
    )[btn_text]


@dataclass
class CitationDocumentUploadModal:
    form: object
    review: Review
    citation_row: Citation
    existing_document: Document | None

    @property
    def modal_id(self):
        return f"citation-document-upload-modal-{self.citation_row.id}"

    @property
    def form_id(self):
        return f"citation-document-upload-form-{self.citation_row.id}"

    def render(self):
        if self.existing_document is not None:
            title = tdt("Replace document")
        else:
            title = tdt("Upload document")

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
        if self.existing_document is not None:
            submit_label = tdt("Replace document")
        else:
            submit_label = tdt("Upload document")

        return h.form(
            id=self.form_id,
            method="post",
            enctype="multipart/form-data",
            novalidate=True,
            hx_post=reverse(
                "citation_upload_pdf_document_modal",
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
                )[submit_label]
            ],
        ]


def DocumentWorkflowCitationRow(
    citation_row,
    *,
    row_id,
    workflow_status,
    actions,
):
    text_extraction_badge = TextExtractionBadge(citation_row)
    figure_extraction_badge = FigureExtractionBadge(citation_row)

    return h.div(
        ".list-group-item.citation-item.position-relative.pb-4",
        id=row_id,
    )[
        h.div(".d-flex.justify-content-between.align-items-start.gap-3")[
            h.div(".flex-grow-1")[
                h.div(".fw-semibold")[
                    citation_row.title or tdt("Untitled citation")
                ],
                (
                    h.div(".text-muted.small.mt-1")[citation_row.abstract]
                    if citation_row.abstract
                    else None
                ),
                h.div(".d-flex.flex-wrap.gap-2.mt-2.small")[
                    h.div[
                        h.span(".text-muted.me-1")[tdt("Document")],
                        DocumentUploadBadge(citation_row),
                    ],
                    (
                        h.div[
                            h.span(".text-muted.me-1")[tdt("Text extraction")],
                            text_extraction_badge,
                        ]
                        if text_extraction_badge is not None
                        else None
                    ),
                    (
                        h.div[
                            h.span(".text-muted.me-1")[
                                tdt("Figure extraction")
                            ],
                            figure_extraction_badge,
                        ]
                        if figure_extraction_badge is not None
                        else None
                    ),
                    workflow_status,
                ],
            ],
            h.div(".d-flex.flex-column.align-items-end.gap-2")[actions],
        ],
    ]


def PdfViewerAssets(
    citation_row: Citation,
    review: Review,
    data_id: str,
    metadata_route_name: str,
):
    pdf_url = None
    metadata_url = None
    if citation_row.document_id is not None:
        pdf_url = reverse(
            "citation_download_pdf_document",
            args=[review.id, citation_row.id],
        )
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


def PdfWorkflowPageContent(
    *,
    assets,
    breadcrumbs,
    title,
    progress_navigation,
    pdf_panel,
    citation_panel,
    results_panel,
):
    return [
        assets,
        breadcrumbs,
        h.h1[title],
        progress_navigation,
        h.div(".row.g-4.citation-workflow-layout")[
            h.div(".col-lg-9")[pdf_panel],
            h.div(".col-lg-3.citation-workflow-sidebar")[
                h.div(".vstack.gap-4")[
                    citation_panel,
                    results_panel,
                ]
            ],
        ],
    ]


def DocumentWorkflowCitationPanel(
    citation_row,
    review,
    *,
    workflow_control,
    workflow_ready,
    rerun_action,
):
    text_extraction_badge = TextExtractionBadge(citation_row)
    if text_extraction_badge is None:
        text_extraction_badge = NotStartedBadge()

    figure_extraction_badge = FigureExtractionBadge(citation_row)
    if figure_extraction_badge is None:
        figure_extraction_badge = NotStartedBadge()

    document = citation_row.document
    return h.section(".border.rounded.p-3.bg-body-tertiary")[
        h.h2(".h5.mb-3")[tdt("Citation")],
        h.div(
            ".fw-semibold",
            title=citation_row.title or None,
        )[Truncator(citation_row.title or tdt("Untitled citation")).chars(60)],
        h.div(".vstack.gap-2.mt-3.small")[
            DocumentUploadControl(citation_row, review),
            DocumentExtractionControl(
                citation_row,
                review,
                text_extraction_badge,
                figure_extraction_badge,
                workflow_ready,
            ),
            workflow_control,
        ],
        (
            DocumentMoreDetails(
                citation_row,
                review,
                rerun_action=rerun_action,
            )
            if document is not None
            else None
        ),
    ]


def DocumentUploadControl(citation_row, review):
    return h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
        h.div[
            h.span(".text-muted.me-1")[tdt("Document")],
            DocumentUploadBadge(citation_row),
        ],
        (
            render_pdf_modal_button(citation_row, review)
            if citation_row.document is None
            else None
        ),
    ]


def DocumentExtractionControl(
    citation_row,
    review,
    text_extraction_badge,
    figure_extraction_badge,
    workflow_ready,
):
    return h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
        h.div[
            h.span(".text-muted.me-1")[tdt("Text extraction")],
            text_extraction_badge,
        ],
        h.div[
            h.span(".text-muted.me-1")[tdt("Figure extraction")],
            figure_extraction_badge,
        ],
        (
            render_pdf_modal_button(citation_row, review)
            if citation_row.document is not None and not workflow_ready
            else None
        ),
    ]


def DocumentMoreDetails(
    citation_row,
    review,
    *,
    rerun_action,
):
    document = citation_row.document
    text_extraction_result = getattr(document, "text_extraction_result", None)
    if text_extraction_result is None:
        text_extraction_status = tdt("No text extraction result yet")
    else:
        text_extraction_status = TextExtractionResult.TextExtractionStatus(
            text_extraction_result.status
        ).label

    return h.details(".mt-3")[
        h.summary[tdt("More")],
        h.div(".mt-3")[
            h.div(".small.text-muted")[document.file.name],
            h.div(".mt-2")[
                h.strong[tdt("Text extraction status")],
                ": ",
                text_extraction_status,
            ],
            h.div(".d-flex.gap-2.flex-wrap")[
                render_pdf_modal_button(citation_row, review),
                rerun_action,
            ],
        ],
    ]


def WorkflowResultsPanel(
    *,
    title,
    results,
    empty_message,
    render_result,
):
    return h.section(".border.rounded.p-3")[
        h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
            h.h2(".h5.mb-0")[title],
            h.div(".text-muted.small")[
                tdt("Results"),
                " ",
                str(len(results)),
            ],
        ],
        (
            h.div(".vstack.gap-3")[
                [render_result(result) for result in results]
            ]
            if results
            else h.p(".text-muted.mb-0")[empty_message]
        ),
    ]


def EvidenceDefinitionItems(result):
    return [
        (
            tdt("Evidence sentences"),
            render_evidence_chips(
                result.evidence_sentences,
                "sentence",
                tdt("Sentence"),
                tdt("Evidence sentences"),
            ),
        ),
        (
            tdt("Evidence tables"),
            render_evidence_chips(
                result.evidence_tables,
                "table",
                tdt("Table"),
                tdt("Evidence tables"),
            ),
        ),
        (
            tdt("Evidence figures"),
            render_evidence_chips(
                result.evidence_figures,
                "figure",
                tdt("Figure"),
                tdt("Evidence figures"),
            ),
        ),
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
