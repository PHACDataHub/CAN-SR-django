from dataclasses import dataclass

from django.http import HttpResponse
from django.views import View

from proj.htpy import definition_list as DefList
from proj.htpy.modal_component import ModalComponent

from my_app.models import (
    CitationDatasetRow,
    L1ScreeningQuestion,
    L1ScreeningResult,
    ScreeningResultStatus,
    SystematicReview,
)
from my_app.queries import L1ScreeningStatusFetcher
from my_app.router import route
from my_app.services.ai_screening import DeferredL1ScreeningService
from my_app.views.view_utils import (
    MustAccessSystematicReviewMixin,
    url_with_same_params,
)
from shortcuts import BasePageTemplate, HtpyTemplateMixin, ListView
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, get_object_or_404, get_request
from shortcuts import htpy as h
from shortcuts import reverse, tdt

SCREENING_STATUS_BADGE_CLASSES = {
    ScreeningResultStatus.NOT_STARTED: "bg-secondary",
    ScreeningResultStatus.PENDING: "bg-warning text-dark",
    ScreeningResultStatus.COMPLETED: "bg-success",
    ScreeningResultStatus.ABANDONED: "bg-danger",
}


def get_page_number(request) -> int:
    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page_number = 1

    return max(page_number, 1)


def CitationRowDisplay(
    citation_row: CitationDatasetRow, review: SystematicReview
):
    request = get_request()
    details_url = reverse(
        "screen_l1_row_details", args=[review.id, citation_row.id]
    )

    fetcher = L1ScreeningStatusFetcher.get_instance()
    status = fetcher.get(citation_row.id)

    if status is ScreeningResultStatus.NOT_STARTED:
        screen_action_url = url_with_same_params(
            request,
            path=reverse(
                "screen_l1_row",
                args=[review.id, citation_row.id],
            ),
            page=get_page_number(request),
        )
        button_markup = (
            h.button(
                ".btn.btn-outline-primary.btn-sm",
                type="button",
                hx_post=screen_action_url,
                hx_target="closest .citation-item",
                hx_swap="innerHTML",
                hx_disabled_elt="this",
            )[tdt("Screen this row")],
        )
    else:
        button_markup = h.button(
            ".btn.btn-outline-secondary.btn-sm.btn-disabled.disabled",
            type="button",
            disabled=True,
        )[tdt("Screening")]

    row_id = f"l1-screening-row-{citation_row.id}"

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
            hx_get=details_url,
            hx_target="#modal-slot",
            hx_swap="innerHTML",
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
        class_=f"badge rounded-pill {SCREENING_STATUS_BADGE_CLASSES[status]}",
    )[status.label]


@dataclass
class L1ScreeningComponent:
    review: SystematicReview
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse("screening_l1_component", args=[self.review.id])

    @property
    def shell_url(self):
        return reverse("screening_l1", args=[self.review.id])

    @property
    def page_number(self):
        return self.page_obj.number

    @cached_property
    def citation_rows(self):
        return CitationDatasetRow.objects.filter(
            dataset__systematic_review=self.review
        ).order_by("order")

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
                citation__dataset__systematic_review=self.review
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
            hx_trigger="click from:#refresh-button",
            hx_swap="outerHTML",
            hx_disabled_elt="#refresh-button",
        )[
            h.div(".row.g-4")[
                h.div(".col-lg-5")[self.render_progress_panel()],
                h.div(".col-lg-7")[self.render_citations_panel()],
            ]
        ]

    def render_progress_panel(self):
        if self.total_citations > 0:
            progress_percent = int(
                (self.screened_citations / self.total_citations) * 100
            )
        else:
            progress_percent = 0

        return h.section(
            id="l1-screening-progress-panel",
            class_="border rounded p-3 bg-body-tertiary",
        )[
            h.h2(".h5.mb-3")[tdt("Progress")],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Total citations")],
                h.span(".fw-semibold")[str(self.total_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Screened so far")],
                h.span(".fw-semibold")[str(self.screened_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.span[tdt("Screening questions")],
                h.span(".fw-semibold")[str(len(self.screening_questions))],
            ],
            h.div(".progress", role="progressbar")[
                h.div(
                    ".progress-bar",
                    style=f"width: {progress_percent}%",
                    aria_valuenow=str(progress_percent),
                    aria_valuemin="0",
                    aria_valuemax="100",
                )[f"{progress_percent}%"],
            ],
        ]

    def render_citations_panel(self):
        if self.page_rows:
            rows = [
                CitationRowDisplay(row, self.review) for row in self.page_rows
            ]
        else:
            rows = [h.p(".text-muted.mb-0")[tdt("No citations on this page.")]]

        return h.section(".border.rounded.p-3")[
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.h2(".h5.mb-0")[tdt("Citations")],
                h.div(".text-muted.small")[
                    tdt("Page"),
                    " ",
                    str(self.page_number),
                ],
            ],
            self.render_pagination_controls(),
            h.div(".list-group")[rows],
        ]

    def render_pagination_controls(self):
        common_button_attrs = {
            "hx_target": "#l1-screening-component",
            "hx_swap": "outerHTML",
            "hx_disabled_elt": "this",
            "type": "button",
            "class": "btn btn-outline-primary btn-sm",
        }
        previous_button = h.button(
            hx_get=(
                self.page_url(
                    self.page_obj.previous_page_number(), self.component_url
                )
                if self.page_obj.has_previous()
                else None
            ),
            disabled=not self.page_obj.has_previous(),
            **common_button_attrs,
        )[tdt("Previous")]

        next_button = h.button(
            hx_get=(
                self.page_url(
                    self.page_obj.next_page_number(), self.component_url
                )
                if self.page_obj.has_next()
                else None
            ),
            disabled=not self.page_obj.has_next(),
            **common_button_attrs,
        )[tdt("Next")]

        return h.div(
            ".d-flex.justify-content-between.align-items-center.mb-3"
        )[
            h.div(".small.text-muted")[
                tdt("Page"),
                " ",
                str(self.page_number),
                " ",
                tdt("of"),
                " ",
                str(self.page_obj.paginator.num_pages),
            ],
            h.div(".btn-group")[
                previous_button,
                next_button,
            ],
        ]

    def page_url(self, page_number, path):
        return url_with_same_params(
            self.request,
            path=path,
            page=page_number,
        )


class L1ScreeningPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["systematic_review"]
        page_obj = self.context["page_obj"]
        component = L1ScreeningComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return [
            bc.BreadcrumbTrailForSystematicReview(review)[
                bc.BreadcrumbItem(label=tdt("L1 Screening")),
            ],
            h.h1[tdt("L1 Screening")],
            h.div(".mb-3")[
                h.button(
                    "#refresh-button.btn.btn-outline-secondary",
                    type="button",
                )[tdt("Refresh")],
            ],
            component.render(),
        ]


class L1ScreeningBaseView(MustAccessSystematicReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return CitationDatasetRow.objects.filter(
            dataset__systematic_review=self.systematic_review
        ).order_by("order")


@route("/systematic-reviews/<int:pk>/screening_l1/", name="screening_l1")
class ScreeningL1PageView(L1ScreeningBaseView, HtpyTemplateMixin):
    template_component = L1ScreeningPageTemplate


@route(
    "/systematic-reviews/<int:pk>/screening_l1/component/",
    name="screening_l1_component",
)
class ScreeningL1ComponentView(L1ScreeningBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = L1ScreeningComponent(
            review=self.systematic_review,
            page_obj=page_obj,
            request=self.request,
        )

        new_page_url = reverse(
            "screening_l1", args=[self.systematic_review.id]
        )
        response_headers = {
            "HX-Push-Url": url_with_same_params(
                self.request,
                path=new_page_url,
                page=page_obj.number,
            )
        }

        return HttpResponse(
            str(component.render()),
            headers=response_headers,
            **response_kwargs,
        )


@route(
    "/systematic-reviews/<int:pk>/screening_l1/rows/<int:row_pk>/",
    name="screen_l1_row",
)
class ScreenL1RowView(MustAccessSystematicReviewMixin, View):
    @cached_property
    def citation_row(self):
        return CitationDatasetRow.objects.get(
            pk=self.kwargs["row_pk"],
            dataset__systematic_review=self.systematic_review,
        )

    @cached_property
    def screening_questions(self):
        return list(
            L1ScreeningQuestion.objects.filter(
                review=self.systematic_review
            ).prefetch_related("options")
        )

    def post(self, request, *args, **kwargs):
        DeferredL1ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
        ).perform()

        headers = {
            "HX-Refocus": "#" + badge_id(self.citation_row),
        }

        return HttpResponse(
            str(CitationRowDisplay(self.citation_row, self.review)),
            headers=headers,
        )


@route(
    "/systematic-reviews/<int:pk>/screening_l1/rows/<int:row_pk>/details/",
    name="screen_l1_row_details",
)
class L1ScreeningRowDetailsView(MustAccessSystematicReviewMixin, View):
    @cached_property
    def citation_row(self):
        return get_object_or_404(
            CitationDatasetRow,
            pk=self.kwargs["row_pk"],
            dataset__systematic_review=self.systematic_review,
        )

    @cached_property
    def screening_columns(self):
        return list(self.citation_row.dataset.screening_columns.order_by("id"))

    @cached_property
    def screening_results(self):
        return list(
            L1ScreeningResult.objects.filter(citation=self.citation_row)
            .select_related("question", "selected_option")
            .order_by("question_id")
        )

    @cached_property
    def included_field_pairs(self):
        included_columns = self.screening_columns

        return [
            (
                tdt("Title"),
                self.citation_row.title or tdt("Untitled citation"),
            ),
            (tdt("Abstract"), self.citation_row.abstract or tdt("None")),
            *[
                (
                    column.name,
                    DefList.render_dl_value(
                        self.citation_row.data.get(column.name)
                    ),
                )
                for column in included_columns
            ],
        ]

    @cached_property
    def included_field_names(self):
        return [column.name for column in self.screening_columns]

    @cached_property
    def non_included_fields(self):
        return [
            (key, DefList.render_dl_value(value))
            for key, value in self.citation_row.data.items()
            if key not in self.included_field_names
        ]

    def render_screening_result(self, result):
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

        notes_content = result.explanation or tdt("None")

        return DefList.DL(
            [
                (tdt("Question"), result.question.question_text),
                (
                    tdt("Status"),
                    ScreeningResultStatus(result.status).label,
                ),
                (tdt("Selected option"), selected_option_content),
                (tdt("Notes"), notes_content),
            ]
        )

    def get(self, *args, **kwargs):
        modal_body = h.fragment[
            h.h2(".h5.mt-4")[tdt("L1 screening results")],
            (
                h.div(".vstack.gap-3")[
                    [
                        self.render_screening_result(result)
                        for result in self.screening_results
                    ]
                ]
                if self.screening_results
                else h.p(".mb-0.text-muted")[tdt("No screening results yet.")]
            ),
            h.h2(".h5")[tdt("Included fields")],
            DefList.DL(self.included_field_pairs),
            h.details(".mt-3")[
                h.summary[tdt("Non-included fields")],
                h.div(".mt-3")[DefList.DL(self.non_included_fields)],
            ],
        ]

        title = h.span[
            tdt("Screening details for"),
            " ",
            self.citation_row.title or tdt("Untitled citation"),
        ]

        return HttpResponse(
            str(
                ModalComponent(
                    title=title,
                    modal_id=f"l1-screening-details-modal-{self.citation_row.id}",
                    size_cls="modal-xl",
                )[modal_body]
            )
        )
