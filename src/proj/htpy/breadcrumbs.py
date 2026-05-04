from typing import Optional

from django.urls import reverse

import htpy as h

from proj.text import tdt


@h.with_children
def BreadcrumbTrail(children):
    return h.nav(aria_label=tdt("breadcrumb"))[
        h.ol(".breadcrumb.mb-3")[children],
    ]


def BreadcrumbItem(label, href: Optional[str] = None):
    if href:
        return h.li(".breadcrumb-item")[h.a(href=href)[label]]

    return h.li(".breadcrumb-item.active", aria_current="page")[label]


def ListSystematicReviewsItem():
    return BreadcrumbItem(
        label=tdt("Systematic Reviews"), href=reverse("systematic_review_list")
    )


def SystematicReviewRootItem(sr):
    return BreadcrumbItem(
        label=sr.title,
        href=reverse("systematic_review_detail", args=[sr.id]),
    )


@h.with_children
def BreadcrumbTrailForSystematicReview(children, sr):
    return BreadcrumbTrail()[
        ListSystematicReviewsItem(),
        SystematicReviewRootItem(sr),
        h.fragment[children],
    ]
