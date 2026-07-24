from django.http import Http404

from my_app.models import Citation
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    DetailView,
    HtpyTemplateMixin,
    ListView,
    View,
    cached_property,
)


def document_citations_for_review(review):
    return (
        Citation.objects.filter(dataset__review=review)
        .select_related(
            "document",
            "document__text_extraction_result",
            "document__figure_extraction_result",
        )
        .order_by("order")
    )


class DocumentCitationListView(MustAccessReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return document_citations_for_review(self.review)


class DocumentCitationDetailView(
    MustAccessReviewMixin,
    DetailView,
    HtpyTemplateMixin,
):
    model = Citation
    pk_url_kwarg = "row_pk"

    def get_queryset(self):
        return document_citations_for_review(self.review)


class DocumentCitationMixin(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        try:
            return document_citations_for_review(self.review).get(
                pk=self.kwargs["row_pk"],
            )
        except Citation.DoesNotExist as exc:
            raise Http404 from exc

    @property
    def document(self):
        document = self.citation_row.document
        if document is None:
            raise Http404

        return document
