import htpy as h

from proj.htpy import breadcrumbs as bc

from my_app.tables.components import TableNavigation
from my_app.tables.table_framework import TableComponent, TableView
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import BasePageTemplate, HtpyTemplateMixin


class ReviewTablePage(BasePageTemplate):
    table_component_class = TableComponent

    def content(self):
        review = self.context["review"]
        title = self.context["table_def"].title
        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=title)
            ],
            h.h1[title],
            TableNavigation(review),
            self.table_component_class(
                page_obj=self.context["page_obj"],
                columns=self.context["columns"],
                column_selection_form=self.context["column_selection_form"],
                filter_forms=self.context["filter_forms"],
                sort_form=self.context["sort_form"],
                request=self.request,
                title=title,
            ),
        ]


class ReviewTableView(MustAccessReviewMixin, TableView, HtpyTemplateMixin):
    template_component = ReviewTablePage

    def get_table_def_kwargs(self):
        return {**super().get_table_def_kwargs(), "review": self.review}
