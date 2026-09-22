from dataclasses import dataclass

import htpy as h

from proj.htpy import definition_list as DefList
from proj.htpy.components import PercentFormatter
from proj.htpy.util import polling_attrs

from my_app.models import (
    Citation,
    Parameter,
    ParameterAnswerAgreement,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    Review,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.queries import (
    ParameterExtractionStatusFetcher,
    ReviewStage,
    get_citations_for_stage,
    get_parameter_extraction_progress_stats,
    get_parameter_human_ai_agreements,
)
from my_app.router import route
from my_app.views.pdf_components import (
    DocumentWorkflowCitationPanel,
    DocumentWorkflowCitationRow,
    EvidenceDefinitionItems,
    PdfPanel,
    PdfViewerAssets,
    PdfWorkflowPageContent,
    WorkflowResultsPanel,
    render_pdf_detail_link,
    render_pdf_modal_button,
)
from my_app.views.screening.components import (
    Badge,
    CitationScreeningProgressNav,
    PaginatedCitationPanel,
    WorkflowListPageContent,
    WorkflowProgressPanel,
    human_review_control_id,
    render_answer_timestamp,
)
from my_app.views.screening.document_util_components import (
    DocumentCitationListView,
)
from my_app.views.screening.util import (
    BADGE_CLASSES,
    can_start_parameter_extraction,
)
from my_app.views.view_utils import (
    paginated_component_response,
    url_with_same_params,
)
from shortcuts import BasePageTemplate, HtpyTemplateMixin
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, reverse, tdt


def ParameterExtractionBadge(citation_row: Citation, status_fetcher):
    status = status_fetcher.get(citation_row.id)
    return Badge(
        status.label,
        BADGE_CLASSES[status],
        badge_id=f"parameter-extraction-row-status-{citation_row.id}",
    )


def parameter_extraction_control_id(citation_row):
    return f"parameter-extraction-control-{citation_row.id}"


def parameter_extraction_human_review_control_id(result):
    return human_review_control_id("parameter-extraction", result)


def render_parameter_answer_values(found, value, selected_option=None):
    found_value = tdt("Yes") if found else tdt("No")
    displayed_value = selected_option.name if selected_option else value
    return h.div[
        h.div(".fw-semibold")[tdt("Found"), ": ", found_value],
        h.div(".small.text-muted")[
            tdt("Value"), ": ", displayed_value or tdt("None")
        ],
    ]


def render_parameter_human_answer_row(
    answer, *, label, edit_url=None, edit_button_id=None
):
    edit_button = None
    if edit_url is not None:
        edit_button = h.button(
            ".btn.btn-outline-secondary.btn-sm",
            id=edit_button_id,
            type="button",
            hx_get=edit_url,
            hx_target="#modal-slot",
            hx_swap="innerHTML",
        )[tdt("Edit")]

    agreement_classes = {
        ParameterAnswerAgreement.DETECTION_DISAGREEMENT: "text-bg-danger",
        ParameterAnswerAgreement.ABSENCE_AGREEMENT: "text-bg-success",
        ParameterAnswerAgreement.VALUE_AGREEMENT: "text-bg-success",
        ParameterAnswerAgreement.VALUE_DISAGREEMENT: "text-bg-secondary",
    }
    agreement = ParameterAnswerAgreement(answer.agreement)

    return h.div(".border-top.pt-3")[
        h.div(".d-flex.flex-wrap.justify-content-between.gap-2.mb-2")[
            h.div[
                h.strong[label],
                " ",
                render_answer_timestamp(answer.updated_at),
            ],
            h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
                h.span(f".badge.{agreement_classes[agreement]}")[
                    agreement.label
                ],
                edit_button,
            ],
        ],
        render_parameter_answer_values(
            answer.found, answer.value, answer.selected_option
        ),
        h.p(".small.mt-2.mb-0")[answer.notes] if answer.notes else None,
    ]


def render_parameter_human_review_control(
    result,
    review,
    current_user,
    answers=None,
):
    if answers is None:
        answers = (
            get_parameter_human_ai_agreements(result.question.review_id)
            .filter(citation=result.citation, question=result.question)
            .select_related("user", "selected_option")
            .order_by("-updated_at", "-id")
        )

    answers = list(answers)
    control_id = parameter_extraction_human_review_control_id(result)
    answer_url = reverse(
        "parameter_extraction_citation_human_answer",
        args=[review.id, result.id],
    )
    current_answer = next(
        (answer for answer in answers if answer.user_id == current_user.id),
        None,
    )
    other_answers = [
        answer for answer in answers if answer is not current_answer
    ]

    validate_button = None
    if not answers:
        validate_button = h.button(
            ".btn.btn-success.btn-sm",
            id=f"parameter-extraction-validate-answer-{result.id}",
            type="button",
            hx_post=reverse(
                "parameter_extraction_citation_validate_ai_answer",
                args=[review.id, result.id],
            ),
            hx_target=f"#{control_id}",
            hx_swap="morph:outerHTML",
        )[tdt("Validate")]

    ai_row = h.div[
        h.div(".d-flex.flex-wrap.justify-content-between.gap-2.mb-2")[
            h.div[
                h.strong[tdt("AI answer")],
                " ",
                render_answer_timestamp(result.updated_at),
            ],
        ],
        render_parameter_answer_values(
            result.found, result.value, result.selected_option
        ),
        (
            h.p(".small.mt-2.mb-0")[result.explanation]
            if result.explanation
            else None
        ),
        h.div(".mt-2")[validate_button] if validate_button else None,
    ]

    human_rows = []
    if current_answer is not None:
        human_rows.append(
            render_parameter_human_answer_row(
                current_answer,
                label=tdt("Your answer"),
                edit_url=answer_url,
                edit_button_id=(
                    f"parameter-extraction-human-answer-action-{result.id}"
                ),
            )
        )

    for answer in other_answers:
        author = answer.user
        author_name = (
            author.get_full_name() or author.get_username()
            if author is not None
            else tdt("Unknown user")
        )
        human_rows.append(
            render_parameter_human_answer_row(answer, label=author_name)
        )

    add_button = None
    if current_answer is None:
        add_button = h.div(".border-top.pt-3")[
            h.button(
                ".btn.btn-outline-primary.btn-sm",
                id=f"parameter-extraction-human-answer-action-{result.id}",
                type="button",
                hx_get=answer_url,
                hx_target="#modal-slot",
                hx_swap="innerHTML",
            )[tdt("Add your answer")]
        ]

    return h.div(".vstack.gap-3", id=control_id)[
        ai_row,
        human_rows,
        add_button,
    ]


def render_parameter_extraction_control(
    citation_row,
    review,
    status_fetcher=None,
):
    if status_fetcher is None:
        status_fetcher = ParameterExtractionStatusFetcher.get_instance()

    status = status_fetcher.get(citation_row.id)
    can_start = can_start_parameter_extraction(citation_row)
    button = None
    if status is ScreeningResultStatus.NOT_STARTED and can_start:
        button = h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "parameter_extraction_citation_process_extraction",
                args=[review.id, citation_row.id],
            ),
            hx_target="closest .parameter-extraction-control",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Extract parameters")]

    return h.div(
        ".parameter-extraction-control.d-flex.flex-wrap.align-items-center.gap-2",
        id=parameter_extraction_control_id(citation_row),
    )[
        h.div[
            h.span(".text-muted.me-1")[tdt("Parameter extraction")],
            ParameterExtractionBadge(citation_row, status_fetcher),
        ],
        button,
    ]


def ParameterCitationRowDisplay(
    citation_row: Citation,
    review: Review,
    status_fetcher,
):
    return DocumentWorkflowCitationRow(
        citation_row,
        row_id=f"parameter-extraction-row-{citation_row.id}",
        workflow_status=h.div[
            h.span(".text-muted.me-1")[tdt("Parameter extraction")],
            ParameterExtractionBadge(citation_row, status_fetcher),
        ],
        actions=[
            render_pdf_detail_link(
                citation_row,
                review,
                "parameter_extraction_citation_detail",
            ),
            render_pdf_modal_button(citation_row, review),
        ],
    )


@dataclass
class ParameterExtractionComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse(
            "parameter_extraction_citations_list_partial",
            args=[self.review.id],
        )

    @property
    def page_number(self):
        return self.page_obj.number

    @cached_property
    def page_rows(self):
        return list(self.page_obj.object_list)

    @cached_property
    def page_row_ids(self):
        return [row.id for row in self.page_rows]

    @cached_property
    def parameters(self):
        return list(
            Parameter.active_objects.filter(review=self.review).order_by("id")
        )

    @cached_property
    def total_citations(self):
        return self.citation_rows.count()

    @cached_property
    def citation_rows(self):
        return get_citations_for_stage(
            self.review.id, ReviewStage.PARAMETER_EXTRACTION
        )

    @cached_property
    def uploaded_citations(self):
        return (
            self.citation_rows.filter(document__isnull=False)
            .values_list("id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def processed_citations(self):
        return (
            self.citation_rows.filter(
                document__text_extraction_result__status=TextExtractionResult.TextExtractionStatus.COMPLETED,
            )
            .values_list("id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def extracted_citations(self):
        return (
            ParameterExtractionResult.objects.filter(
                citation__in=self.citation_rows
            )
            .values_list("citation_id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def status_fetcher(self):
        fetcher = ParameterExtractionStatusFetcher.get_instance()
        fetcher.prefetch_keys(self.page_row_ids)
        return fetcher

    def render(self):
        return h.div(
            id="parameter-extraction-component",
            hx_target="this",
            hx_get=self.page_url(self.page_number, self.component_url),
            hx_swap="morph:outerHTML",
            hx_disabled_elt="#refresh-button",
            **polling_attrs(
                "click from:#refresh-button, citations-update from:body"
            ),
        )[
            h.div(".row.g-4")[
                h.div(".col-lg-5")[self.render_progress_panel()],
                h.div(".col-lg-7")[self.render_citations_panel()],
            ]
        ]

    def render_progress_panel(self):
        return WorkflowProgressPanel(
            "parameter-extraction-progress-panel",
            metrics=[
                (tdt("Total citations"), self.total_citations),
                (tdt("Uploaded documents"), self.uploaded_citations),
                (tdt("Text extracted documents"), self.processed_citations),
                (tdt("Extracted so far"), self.extracted_citations),
                (tdt("Parameters"), len(self.parameters)),
            ],
            completed=self.extracted_citations,
            total=self.total_citations,
        )

    def render_citations_panel(self):
        rows = [
            ParameterCitationRowDisplay(
                row,
                self.review,
                self.status_fetcher,
            )
            for row in self.page_rows
        ]
        return PaginatedCitationPanel(
            component_id="parameter-extraction-component",
            component_url=self.component_url,
            page_obj=self.page_obj,
            request=self.request,
            rows=rows,
        )

    def page_url(self, page_number, path):
        return url_with_same_params(
            self.request,
            path=path,
            page=page_number,
        )


class ParameterExtractionPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["review"]
        page_obj = self.context["page_obj"]
        component = ParameterExtractionComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return WorkflowListPageContent(
            review,
            tdt("Parameter extraction"),
            component.render(),
        )


class ParameterExtractionPdfPage(BasePageTemplate):
    @property
    def citation_row(self) -> Citation:
        return self.context["object"]

    @property
    def review(self):
        return self.context["review"]

    def content(self):
        review = self.review
        citation_row = self.citation_row

        return PdfWorkflowPageContent(
            assets=PdfViewerAssets(
                citation_row,
                review,
                data_id="parameter-extraction-citation-data",
                metadata_route_name="parameter_extraction_citation_pdf_metadata",
            ),
            breadcrumbs=bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("Parameter extraction"),
                    href=reverse(
                        "parameter_extraction_citations_list", args=[review.id]
                    ),
                ),
                bc.BreadcrumbItem(label=tdt("PDF extraction")),
            ],
            title=tdt("Parameter PDF extraction"),
            progress_navigation=CitationScreeningProgressNav(
                citation_row,
                review,
                stage=ReviewStage.PARAMETER_EXTRACTION,
                detail_route_name="parameter_extraction_citation_detail",
                progress_stats=get_parameter_extraction_progress_stats(
                    review.id
                ),
                nav_label=tdt("Parameter extraction citation navigation"),
            ),
            pdf_panel=PdfPanel(citation_row),
            citation_panel=self.render_citation_panel(citation_row),
            results_panel=self.render_results_panel(citation_row),
        )

    def render_citation_panel(self, citation_row: Citation):
        status_fetcher = ParameterExtractionStatusFetcher.get_instance()
        workflow_ready = can_start_parameter_extraction(citation_row)
        rerun_action = None
        if (
            status_fetcher.get(citation_row.id)
            is not ScreeningResultStatus.NOT_STARTED
            and workflow_ready
        ):
            rerun_action = self.render_reextract_button()

        return DocumentWorkflowCitationPanel(
            citation_row,
            self.review,
            workflow_control=render_parameter_extraction_control(
                citation_row,
                self.review,
                status_fetcher,
            ),
            workflow_ready=workflow_ready,
            rerun_action=rerun_action,
        )

    def render_reextract_button(self):
        return h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "parameter_extraction_citation_process_extraction",
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target=f"#{parameter_extraction_control_id(self.citation_row)}",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Re-extract")]

    def render_results_panel(self, citation_row: Citation):
        results = self.get_results(citation_row)
        self.human_answers_by_question_id = (
            self.get_human_answers_by_question_id(citation_row, results)
        )
        return WorkflowResultsPanel(
            title=tdt("Parameter extraction results"),
            results=results,
            empty_message=tdt("No extraction results yet."),
            render_result=self.render_result,
        )

    def get_results(self, citation_row: Citation):
        return list(
            ParameterExtractionResult.objects.filter(citation=citation_row)
            .select_related("question", "selected_option")
            .order_by("question_id")
        )

    def get_human_answers_by_question_id(self, citation_row, results):
        answers = (
            get_parameter_human_ai_agreements(self.review.id)
            .filter(
                citation=citation_row,
                question_id__in=[result.question_id for result in results],
            )
            .select_related("user", "selected_option")
            .order_by("-updated_at", "-id")
        )
        grouped_answers = {}
        for answer in answers:
            grouped_answers.setdefault(answer.question_id, []).append(answer)
        return grouped_answers

    def render_result(self, result: ParameterExtractionResult):
        return DefList.DL(
            [
                (tdt("Parameter"), result.question.name),
                (
                    tdt("Status"),
                    ScreeningResultStatus(result.status).label,
                ),
                (
                    tdt("Answers"),
                    render_parameter_human_review_control(
                        result,
                        self.review,
                        self.request.user,
                        self.human_answers_by_question_id.get(
                            result.question_id, []
                        ),
                    ),
                ),
                (tdt("Confidence"), PercentFormatter(result.confidence)),
                *EvidenceDefinitionItems(result),
            ]
        )

    def render_human_review_control(self, result: ParameterExtractionResult):
        answers = self.human_answers_by_question_id.get(result.question_id, [])
        return render_parameter_human_review_control(
            result,
            self.review,
            self.request.user,
            answers,
        )


class ParameterExtractionBaseView(DocumentCitationListView):
    stage = ReviewStage.PARAMETER_EXTRACTION


@route(
    "/reviews/<int:review_id>/parameter_extraction/",
    name="parameter_extraction_citations_list",
)
class ParameterExtractionPageView(
    ParameterExtractionBaseView,
    HtpyTemplateMixin,
):
    template_component = ParameterExtractionPageTemplate


@route(
    "/reviews/<int:review_id>/parameter_extraction/component/",
    name="parameter_extraction_citations_list_partial",
)
class ParameterExtractionComponentView(ParameterExtractionBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = ParameterExtractionComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        return paginated_component_response(
            self.request,
            page_obj,
            component.render(),
            reverse(
                "parameter_extraction_citations_list", args=[self.review.id]
            ),
            **response_kwargs,
        )
