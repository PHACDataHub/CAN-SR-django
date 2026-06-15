from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.utils.functional import cached_property
from django.utils.text import Truncator

import htpy as h

from proj.htpy import definition_list as DefList
from proj.htpy.util import static_no_cache

from my_app.models import (
    Citation,
    L2ScreeningQuestion,
    L2ScreeningResult,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.queries import L2ScreeningStatusFetcher
from my_app.router import route
from my_app.services.l2_screening import DeferredL2ScreeningService
from my_app.views.screening_l2 import (
    _document_upload_badge,
    _l2_screening_badge,
    _text_extraction_badge,
    _text_extraction_badge_for_status,
    render_l2_pdf_modal_button,
)
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import BasePageTemplate, DetailView, HtpyTemplateMixin, View
from shortcuts import breadcrumbs as bc
from shortcuts import reverse, tdt


def l2_screening_control_id(citation_row):
    return f"l2-pdf-screening-control-{citation_row.id}"


def can_start_l2_screening(citation_row):
    document = citation_row.document
    if document is None:
        return False

    text_extraction_result = getattr(document, "text_extraction_result", None)
    if text_extraction_result is None:
        return False

    return (
        text_extraction_result.status
        == TextExtractionResult.TextExtractionStatus.COMPLETED
    )


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
            _l2_screening_badge(citation_row, status_fetcher),
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
        pdf_url = None
        metadata_url = None
        if citation_row.document_id is not None:
            pdf_url = reverse(
                "screen_l2_row_pdf", args=[review.id, citation_row.id]
            )
            metadata_url = reverse(
                "screen_l2_row_pdf_metadata",
                args=[review.id, citation_row.id],
            )

        return [
            h.template(
                id="l2-citation-data",
                data_citation_id=str(citation_row.id),
                data_review_id=str(review.id),
                data_pdf_url=pdf_url,
                data_metadata_url=metadata_url,
            ),
            h.script(
                src=static_no_cache("screen_l2_citation.js"),
                type="module",
            ),
            h.link(
                rel="stylesheet",
                href=static_no_cache("screen_l2_citation.css"),
            ),
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("L2 Screening"),
                    href=reverse("screening_l2", args=[review.id]),
                ),
                bc.BreadcrumbItem(label=tdt("PDF screening")),
            ],
            h.h1[tdt("L2 PDF screening")],
            h.div(".row.g-4.l2-screening-layout")[
                h.div(".col-lg-9")[self.render_pdf_panel(citation_row),],
                h.div(".col-lg-3.l2-screening-sidebar")[
                    h.div(".vstack.gap-4")[
                        self.render_citation_panel(citation_row),
                        self.render_results_panel(citation_row),
                    ]
                ],
            ],
        ]

    def render_pdf_panel(self, citation_row: Citation):
        if citation_row.document_id is None:
            initial_status = tdt("Upload a PDF to view the document.")
        else:
            initial_status = tdt("Loading PDF...")

        return h.section(
            ".l2-pdf-panel",
            aria_label=tdt("Citation PDF viewer"),
        )[
            h.div(".l2-pdf-toolbar")[
                h.h2(".h5.mb-0")[tdt("Document")],
                h.span(
                    ".small.text-muted",
                    id="l2-pdf-status",
                    role="status",
                    aria_live="polite",
                )[initial_status],
            ],
            h.div(
                ".l2-pdf-scroll",
                id="l2-pdf-scroll",
                tabindex="0",
            )[
                h.div(".l2-pdf-pages", id="l2-pdf-pages"),
            ],
        ]

    def render_citation_panel(self, citation_row: Citation):
        text_extraction_badge = _text_extraction_badge(citation_row)
        status_fetcher = L2ScreeningStatusFetcher.get_instance()
        document = citation_row.document
        if text_extraction_badge is None:
            text_extraction_badge = _text_extraction_badge_for_status(
                TextExtractionResult.TextExtractionStatus.NOT_STARTED
            )

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
                _document_upload_badge(citation_row),
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
            .select_related("question", "selected_option")
            .order_by("question_id")
        )

    def render_result(self, result: L2ScreeningResult):
        selected_option = result.selected_option
        if selected_option is None:
            selected_option_content = h.span(".text-muted")[
                tdt("No option selected")
            ]
        else:
            selected_option_content = h.div[
                h.div(".fw-semibold")[selected_option.option_text],
                h.div(".small.text-muted")[selected_option.option_value],
            ]

        evidence_tables = ", ".join(
            str(item) for item in result.evidence_tables
        )
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
                (tdt("Selected option"), selected_option_content),
                (tdt("Confidence"), confidence_value),
                (tdt("Notes"), result.explanation or tdt("None")),
                (
                    tdt("Evidence sentences"),
                    self.render_evidence_sentence_chips(result),
                ),
                (tdt("Evidence tables"), evidence_tables or tdt("None")),
            ]
        )

    def render_evidence_sentence_chips(self, result: L2ScreeningResult):
        if not result.evidence_sentences:
            return tdt("None")

        evidence_sentence_list = ", ".join(
            str(sentence_index) for sentence_index in result.evidence_sentences
        )
        return h.div(
            ".d-flex.flex-wrap.gap-2",
            aria_label=f"{tdt('Evidence sentences')}: {evidence_sentence_list}",
        )[
            [
                h.button(
                    ".btn.btn-sm.btn-outline-primary.l2-evidence-chip",
                    type="button",
                    data_sentence_index=str(sentence_index),
                )[tdt("Sentence"), " ", str(sentence_index)]
                for sentence_index in result.evidence_sentences
            ]
        ]


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/details/",
    name="screen_l2_row_details",
)
class L2PdfScreeningView(MustAccessReviewMixin, DetailView, HtpyTemplateMixin):
    model = Citation
    pk_url_kwarg = "row_pk"
    template_component = L2PdfScreeningPage

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__text_extraction_result")
            .order_by("order")
        )


class L2PdfCitationMixin(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        try:
            return Citation.objects.select_related(
                "document", "document__text_extraction_result"
            ).get(
                pk=self.kwargs["row_pk"],
                dataset__review=self.review,
            )
        except Citation.DoesNotExist as exc:
            raise Http404 from exc

    @property
    def document(self):
        document = self.citation_row.document
        if document is None:
            raise Http404
        return document


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/process/",
    name="screen_l2_row_process",
)
class L2PdfScreeningProcessView(L2PdfCitationMixin):
    @cached_property
    def screening_questions(self):
        return list(L2ScreeningQuestion.objects.filter(review=self.review))

    def post(self, request, *args, **kwargs):
        if not can_start_l2_screening(self.citation_row):
            return HttpResponse(
                str(
                    render_l2_screening_control(
                        self.citation_row,
                        self.review,
                    )
                ),
                status=409,
            )

        DeferredL2ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
            overwrite_existing=True,
        ).perform()

        return HttpResponse(
            str(render_l2_screening_control(self.citation_row, self.review))
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/pdf/",
    name="screen_l2_row_pdf",
)
class L2PdfCitationView(L2PdfCitationMixin):
    def get(self, request, *args, **kwargs):
        document_file = self.document.file
        return FileResponse(
            document_file.open("rb"),
            content_type="application/pdf",
            as_attachment=False,
            filename=document_file.name,
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/pdf-metadata/",
    name="screen_l2_row_pdf_metadata",
)
class L2PdfCitationMetadataView(L2PdfCitationMixin):
    def get(self, request, *args, **kwargs):
        text_extraction_result = getattr(
            self.document, "text_extraction_result", None
        )
        if text_extraction_result is None:
            raise Http404

        return JsonResponse(
            {
                "pages": text_extraction_result.pages,
                "highlights": self.get_highlights(text_extraction_result),
            }
        )

    def get_highlights(self, text_extraction_result):
        sentence_texts = text_extraction_result.get_sentence_list()
        evidence_indices = self.get_evidence_indices()
        sentence_coordinates = [
            coordinate
            for coordinate in text_extraction_result.coordinates
            if coordinate.get("type") == "s"
        ]

        highlights = []
        for sentence_index in evidence_indices:
            if sentence_index >= len(sentence_texts):
                continue

            sentence_text = sentence_texts[sentence_index]
            highlights.extend(
                {
                    **coordinate,
                    "sentence_index": sentence_index,
                }
                for coordinate in sentence_coordinates
                if coordinate.get("text") == sentence_text
            )

        return highlights

    def get_evidence_indices(self):
        results = L2ScreeningResult.objects.filter(
            citation=self.citation_row
        ).order_by("question_id")
        evidence_indices = [
            sentence_index
            for result in results
            for sentence_index in result.evidence_sentences
            if isinstance(sentence_index, int) and sentence_index >= 0
        ]
        return list(dict.fromkeys(evidence_indices))
