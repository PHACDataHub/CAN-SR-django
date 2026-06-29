from django.utils.text import Truncator

import htpy as h

from proj.htpy import definition_list as DefList

from my_app.models import (
    Citation,
    L2ScreeningResult,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.queries import (
    L2ScreeningStatusFetcher,
    get_l2_screening_progress_stats,
)
from my_app.views.pdf_components import (
    PdfPanel,
    PdfViewerAssets,
    render_evidence_chips,
)
from my_app.views.screening.components import (
    CitationScreeningProgressNav,
    NotStartedBadge,
)
from my_app.views.screening.l2_common_components import (
    DocumentUploadBadge,
    FigureExtractionBadge,
    L2ScreeningBadge,
    TextExtractionBadge,
    render_l2_human_review_control,
    render_l2_pdf_modal_button,
)
from shortcuts import BasePageTemplate
from shortcuts import breadcrumbs as bc
from shortcuts import reverse, tdt

from .util import can_start_l2_screening


def l2_screening_control_id(citation_row):
    return f"l2-pdf-screening-control-{citation_row.id}"


def render_l2_screening_control(citation_row, review, status_fetcher=None):
    if status_fetcher is None:
        status_fetcher = L2ScreeningStatusFetcher.get_instance()

    status = status_fetcher.get(citation_row.id)
    can_start = can_start_l2_screening(citation_row)
    button = None
    if status is ScreeningResultStatus.NOT_STARTED and can_start:
        button = h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "screen_l2_row_process",
                args=[review.id, citation_row.id],
            ),
            hx_target="closest .l2-pdf-screening-control",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Screen this document")]
    return h.div(
        ".l2-pdf-screening-control.d-flex.flex-wrap.align-items-center.gap-2",
        id=l2_screening_control_id(citation_row),
    )[
        h.div[
            h.span(".text-muted.me-1")[tdt("L2 screening")],
            L2ScreeningBadge(citation_row, status_fetcher),
        ],
        button,
    ]


class L2PdfScreeningPage(BasePageTemplate):
    @property
    def citation_row(self) -> Citation:
        return self.context["object"]

    @property
    def review(self):
        return self.context["review"]

    def content(self):
        review = self.review
        citation_row = self.citation_row

        return [
            PdfViewerAssets(
                citation_row,
                review,
                data_id="l2-citation-data",
                pdf_route_name="screen_l2_row_pdf",
                metadata_route_name="screen_l2_row_pdf_metadata",
            ),
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("L2 Screening"),
                    href=reverse("screening_l2", args=[review.id]),
                ),
                bc.BreadcrumbItem(label=tdt("PDF screening")),
            ],
            h.h1[tdt("L2 PDF screening")],
            CitationScreeningProgressNav(
                citation_row,
                review,
                detail_route_name="screen_l2_row_details",
                progress_stats=get_l2_screening_progress_stats(review.id),
                nav_label=tdt("L2 citation navigation"),
            ),
            h.div(".row.g-4.citation-workflow-layout")[
                h.div(".col-lg-9")[self.render_pdf_panel(citation_row),],
                h.div(".col-lg-3.citation-workflow-sidebar")[
                    h.div(".vstack.gap-4")[
                        self.render_citation_panel(citation_row),
                        self.render_results_panel(citation_row),
                    ]
                ],
            ],
        ]

    def render_pdf_panel(self, citation_row: Citation):
        return PdfPanel(citation_row)

    def render_citation_panel(self, citation_row: Citation):
        text_extraction_badge = (
            TextExtractionBadge(citation_row) or NotStartedBadge()
        )
        figure_extraction_badge = (
            FigureExtractionBadge(citation_row) or NotStartedBadge()
        )
        status_fetcher = L2ScreeningStatusFetcher.get_instance()
        document = citation_row.document

        return h.section(".border.rounded.p-3.bg-body-tertiary")[
            h.h2(".h5.mb-3")[tdt("Citation")],
            h.div(
                ".fw-semibold",
                title=citation_row.title or None,
            )[
                Truncator(
                    citation_row.title or tdt("Untitled citation")
                ).chars(60)
            ],
            h.div(".vstack.gap-2.mt-3.small")[
                self.render_document_upload_control(citation_row),
                self.render_text_extraction_control(
                    citation_row,
                    text_extraction_badge,
                    figure_extraction_badge,
                ),
                render_l2_screening_control(
                    citation_row,
                    self.review,
                    status_fetcher,
                ),
            ],
            (
                self.render_more_details(document, status_fetcher)
                if document is not None
                else None
            ),
        ]

    def render_document_upload_control(self, citation_row):
        return h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
            h.div[
                h.span(".text-muted.me-1")[tdt("Document")],
                DocumentUploadBadge(citation_row),
            ],
            (
                render_l2_pdf_modal_button(citation_row, self.review)
                if citation_row.document is None
                else None
            ),
        ]

    def render_text_extraction_control(
        self,
        citation_row,
        text_extraction_badge,
        figure_extraction_badge,
    ):
        document = citation_row.document
        text_extraction_result = getattr(
            document, "text_extraction_result", None
        )
        is_processed = (
            text_extraction_result is not None
            and text_extraction_result.status
            == TextExtractionResult.TextExtractionStatus.COMPLETED
        )

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
                render_l2_pdf_modal_button(citation_row, self.review)
                if document is not None and not is_processed
                else None
            ),
        ]

    def render_more_details(self, document, status_fetcher):
        text_extraction_result = getattr(
            document, "text_extraction_result", None
        )
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
                    render_l2_pdf_modal_button(self.citation_row, self.review),
                    (
                        self.render_rescreen_button()
                        if status_fetcher.get(self.citation_row.id)
                        is not ScreeningResultStatus.NOT_STARTED
                        and can_start_l2_screening(self.citation_row)
                        else None
                    ),
                ],
            ],
        ]

    def render_rescreen_button(self):
        return h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "screen_l2_row_process",
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target=f"#{l2_screening_control_id(self.citation_row)}",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Re-screen")]

    def render_results_panel(self, citation_row: Citation):
        results = self.get_results(citation_row)

        return h.section(".border.rounded.p-3")[
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.h2(".h5.mb-0")[tdt("L2 screening results")],
                h.div(".text-muted.small")[
                    tdt("Results"),
                    " ",
                    str(len(results)),
                ],
            ],
            (
                h.div(".vstack.gap-3")[
                    [self.render_result(result) for result in results]
                ]
                if results
                else h.p(".text-muted.mb-0")[tdt("No screening results yet.")]
            ),
        ]

    def get_results(self, citation_row: Citation):
        return list(
            L2ScreeningResult.objects.filter(citation=citation_row)
            .select_related(
                "question",
                "selected_option",
                "human_selected_answer",
                "human_validated_by",
            )
            .order_by("question_id")
        )

    def render_result(self, result: L2ScreeningResult):
        if result.confidence is None:
            confidence_value = tdt("None")
        else:
            confidence_value = str(result.confidence)

        return DefList.DL(
            [
                (tdt("Question"), result.question.question_text),
                (
                    tdt("Status"),
                    ScreeningResultStatus(result.status).label,
                ),
                (
                    tdt("Selected option"),
                    render_l2_human_review_control(result, self.review),
                ),
                (tdt("Confidence"), confidence_value),
                (tdt("Notes"), result.explanation or tdt("None")),
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
        )
