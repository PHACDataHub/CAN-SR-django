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


def ListReviewsItem():
    return BreadcrumbItem(
        label=tdt("Systematic Reviews"), href=reverse("review_list")
    )


def ReviewRootItem(review):
    label = review.title
    if review.is_deleted:
        label = f'{label} {tdt("(ARCHIVED)")}'

    return BreadcrumbItem(
        label=label,
        href=reverse("review_detail", args=[review.id]),
    )


@h.with_children
def BreadcrumbTrailForReview(children, review):
    return BreadcrumbTrail()[
        ListReviewsItem(),
        ReviewRootItem(review),
        h.fragment[children],
    ]
