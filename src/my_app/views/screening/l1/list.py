from dataclasses import dataclass

from proj.htpy.util import polling_attrs

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningResult,
    Review,
    ScreeningResultStatus,
)
from my_app.queries import L1ScreeningStatusFetcher
from my_app.router import route
from my_app.views.screening.components import (
    PaginatedCitationPanel,
    WorkflowListPageContent,
    WorkflowProgressPanel,
)
from my_app.views.screening.util import BADGE_CLASSES
from my_app.views.view_utils import (
    MustAccessReviewMixin,
    paginated_component_response,
    url_with_same_params,
)
from shortcuts import (
    BasePageTemplate,
    HtpyTemplateMixin,
    ListView,
    cached_property,
)
from shortcuts import htpy as h
from shortcuts import reverse, tdt


def CitationRowDisplay(citation_row: Citation, review: Review):
    details_url = reverse(
        "l1_citation_detail", args=[review.id, citation_row.id]
    )

    fetcher = L1ScreeningStatusFetcher.get_instance()
    status = fetcher.get(citation_row.id)
    row_id = f"l1-screening-row-{citation_row.id}"

    btn_id = f"l1-screening-row-screen-btn-{citation_row.id}"
    if status is ScreeningResultStatus.NOT_STARTED:
        screen_action_url = reverse(
            "l1_citation_process_screening",
            args=[review.id, citation_row.id],
        )
        button_markup = h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=screen_action_url,
            data_focus_after=f"#{badge_id(citation_row)}",
            hx_target="closest .citation-item",
            hx_select=f"#{row_id}",
            hx_swap="innerHTML",
            hx_disabled_elt="this",
            id=btn_id,
        )[tdt("Screen this row")]
    elif status is ScreeningResultStatus.PENDING:
        button_markup = h.button(
            ".btn.btn-outline-secondary.btn-sm.btn-disabled.disabled",
            type="button",
            aria_disabled=True,
            tabindex="-1",
            id=btn_id,
        )[tdt("Screening...")]
    else:
        button_markup = h.button(
            ".btn.btn-outline-secondary.btn-sm.btn-disabled.disabled",
            type="button",
            aria_disabled=True,
            tabindex="-1",
            id=btn_id,
        )[ScreeningResultStatus(status).label]

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
            ],
            h.div(".d-flex.flex-column.align-items-end.gap-2")[
                CitationRowL1StatusBadge(citation_row), button_markup
            ],
        ],
        h.a(
            ".btn.btn-outline-secondary.btn-sm.position-absolute.bottom-0.end-0.me-3.mb-2",
            href=details_url,
            id=f"l1-screening-row-details-btn-{citation_row.id}",
        )[tdt("View more")],
    ]


def badge_id(citation_row):
    return f"l1-screening-row-status-{citation_row.id}"


def CitationRowL1StatusBadge(citation_row):
    fetcher = L1ScreeningStatusFetcher.get_instance()
    status = fetcher.get(citation_row.id)
    return h.div(
        id=badge_id(citation_row),
        tabindex="-1",
        class_=f"badge rounded-pill {BADGE_CLASSES[status]}",
    )[status.label]


@dataclass
class L1ScreeningComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse("l1_citations_list_partial", args=[self.review.id])

    @property
    def page_number(self):
        return self.page_obj.number

    @cached_property
    def citation_rows(self):
        return Citation.objects.filter(dataset__review=self.review).order_by(
            "order"
        )

    @cached_property
    def page_rows(self):
        return list(self.page_obj.object_list)

    @cached_property
    def page_row_ids(self):
        return [row.id for row in self.page_rows]

    @cached_property
    def screening_questions(self):
        return list(
            L1ScreeningQuestion.objects.filter(
                review=self.review
            ).prefetch_related("options")
        )

    @cached_property
    def total_citations(self):
        return self.citation_rows.count()

    @cached_property
    def screened_citations(self):
        return (
            L1ScreeningResult.objects.filter(
                citation__dataset__review=self.review
            )
            .values_list("citation_id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def status_fetcher(self):
        fetcher = L1ScreeningStatusFetcher.get_instance()
        fetcher.prefetch_keys(self.page_row_ids)
        return fetcher

    def render(self):
        return h.div(
            id="l1-screening-component",
            hx_target="this",
            hx_get=self.page_url(self.page_number, self.component_url),
            hx_swap="morph:outerHTML",
            hx_disabled_elt="#refresh-button",
            hx_sync="this:replace",
            **polling_attrs("click from:#refresh-button"),
        )[
            h.div(".row.g-4")[
                h.div(".col-lg-5")[self.render_progress_panel()],
                h.div(".col-lg-7")[self.render_citations_panel()],
            ]
        ]

    def render_progress_panel(self):
        return WorkflowProgressPanel(
            "l1-screening-progress-panel",
            metrics=[
                (tdt("Total citations"), self.total_citations),
                (tdt("Screened so far"), self.screened_citations),
                (tdt("Screening questions"), len(self.screening_questions)),
            ],
            completed=self.screened_citations,
            total=self.total_citations,
        )

    def render_citations_panel(self):
        rows = [CitationRowDisplay(row, self.review) for row in self.page_rows]
        return PaginatedCitationPanel(
            component_id="l1-screening-component",
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


class L1ScreeningPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["review"]
        page_obj = self.context["page_obj"]
        component = L1ScreeningComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return WorkflowListPageContent(
            review,
            tdt("L1 Screening"),
            component.render(),
        )


class L1ScreeningBaseView(MustAccessReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return Citation.objects.filter(dataset__review=self.review).order_by(
            "order"
        )


@route("/reviews/<int:review_id>/screening_l1/", name="l1_citations_list")
class ScreeningL1PageView(L1ScreeningBaseView, HtpyTemplateMixin):
    template_component = L1ScreeningPageTemplate


@route(
    "/reviews/<int:review_id>/screening_l1/component/",
    name="l1_citations_list_partial",
)
class ScreeningL1ComponentView(L1ScreeningBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = L1ScreeningComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        return paginated_component_response(
            self.request,
            page_obj,
            component.render(),
            reverse("l1_citations_list", args=[self.review.id]),
            **response_kwargs,
        )
