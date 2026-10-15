from django.http import Http404

import htpy as h

from proj.htpy.util import polling_attrs
from proj.text import tdt


def WorkflowRefreshButton():
    return h.div(".mb-3")[
        h.button(
            "#refresh-button.btn.btn-outline-secondary",
            type="button",
        )[tdt("Refresh")],
    ]


def workflow_refresh_attrs(url, *, citations_update=False):
    trigger = "click from:#refresh-button"
    if citations_update:
        trigger += ", citations-update from:body"
    return {
        "class": "workflow-refresh",
        "hx_get": url,
        "hx_target": "this",
        "hx_sync": "body:drop",
        "hx_disabled_elt": "#refresh-button",
        **polling_attrs(trigger),
    }


class WorkflowListRefreshMixin:
    def paginate_queryset(self, queryset, page_size):
        try:
            return super().paginate_queryset(queryset, page_size)
        except Http404:
            if self.request.headers.get("HX-Request") != "true":
                raise
            # Completed tasks can remove the current last page of filtered results.
            paginator = self.get_paginator(queryset, page_size)
            page = paginator.get_page(self.request.GET.get("page", 1))
            return paginator, page, page.object_list, page.has_other_pages()
