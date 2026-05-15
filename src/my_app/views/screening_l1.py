from my_app.models import (
    CitationDataset,
    CitationDatasetColumn,
    CitationDatasetRow,
    CitationQueryResult,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    ScreeningResultStatus,
    SystematicReview,
)
from my_app.router import route
from my_app.views.view_utils import MustAccessSystematicReviewMixin
from shortcuts import (
    BasePageTemplate,
    HtpyComponent,
    HtpyTemplatelessMixin,
    HtpyTemplateMixin,
    ListView,
)
from shortcuts import breadcrumbs as bc
from shortcuts import dataclass
from shortcuts import htpy as h
from shortcuts import reverse, tdt


class L1ScreeningTemplate(BasePageTemplate):
    def content(self):
        review = self.context["systematic_review"]
        return [
            bc.BreadcrumbTrailForSystematicReview(review)[
                bc.BreadcrumbItem(label=tdt("L1 Screening")),
            ],
            h.h1[tdt("L1 Screening")],
            L1ScreeningComponent(
                review=review,
                page_number=1,  # Placeholder for pagination
            ).render(),
        ]


class PaginatedCitationsBase(MustAccessSystematicReviewMixin, ListView):
    # to be used as a base class for a thinner view later
    paginate_by = 25

    def get_queryset(self):
        return CitationDatasetRow.objects.filter(
            dataset__systematic_review=self.review
        ).order_by("order")


@route("/systematic-reviews/<int:pk>/screening_l1/", name="screening_l1")
class ScreeningL1Page(PaginatedCitationsBase, HtpyTemplateMixin):
    template_component = L1ScreeningTemplate


@dataclass
class L1ScreeningComponent(HtpyComponent):
    review: SystematicReview
    page_number: int

    def render(self):
        return h.div(".row")[
            h.div(".col-lg-5")[self.render_progress(),],
            h.div(".col-lg-7")[self.render_page(),],
        ]

    def render_progress(self):
        total_rows = CitationDatasetRow.objects.filter(
            dataset__systematic_review=self.review
        ).count()
        return h.div(".border.p-2.rounded")[
            h.h3["Progress"],
            h.p[f"Total Citations: {total_rows}"],
        ]

    def render_page(self):
        return h.div(".border.p-2.rounded")[
            h.h3[f"Page {self.page_number}"],
            h.p[
                "This is where the screening questions and options would be displayed."
            ],
        ]
