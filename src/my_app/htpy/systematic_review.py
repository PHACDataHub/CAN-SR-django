import htpy as h

from shortcuts import BasePageTemplate, GenericFormWithContainer
from shortcuts import breadcrumbs as bc
from shortcuts import get_token, reverse, tdt, tm


class SystematicReviewListPage(BasePageTemplate):
    def content(self):
        reviews = self.context["object_list"]

        return [
            bc.BreadcrumbTrail()[
                bc.BreadcrumbItem(label=tdt("Systematic Reviews"))
            ],
            h.h1[tdt("Systematic review list")],
            h.div(".mb-3")[
                h.a(
                    href=reverse("create_systematic_review"),
                    class_="btn btn-primary",
                )[tdt("Create systematic review")],
            ],
            (
                h.p(".text-muted")[tdt("No systematic reviews yet.")]
                if not reviews
                else h.ul[
                    [
                        h.li[
                            h.a(
                                href=reverse(
                                    "systematic_review_detail",
                                    args=[review.id],
                                )
                            )[review.title]
                        ]
                        for review in reviews
                    ]
                ]
            ),
        ]


class SystematicReviewCreatePage(BasePageTemplate):

    def content(self):
        return [
            bc.BreadcrumbTrail()[
                bc.ListSystematicReviewsItem(),
                bc.BreadcrumbItem(label=tdt("Create systematic review")),
            ],
            h.h1[tdt("Create systematic review")],
            GenericFormWithContainer(
                self.context["form"],
            ),
        ]


class SystematicReviewEditPage(BasePageTemplate):
    def content(self):
        sr = self.context.get("object")
        return [
            bc.BreadcrumbTrailForSystematicReview(sr)[
                bc.BreadcrumbItem(label=tdt("Edit"))
            ],
            h.h1[tdt("Edit systematic review")],
            GenericFormWithContainer(
                self.context["form"],
            ),
        ]


class SystematicReviewDetailPage(BasePageTemplate):
    def content(self):
        review = self.context["object"]
        citation_upload_url = reverse("citation_upload", args=[review.id])
        import_citation_dataset_link = (
            h.a(
                href=citation_upload_url,
                class_="btn btn-outline-primary disabled",
                aria_disabled="true",
                tabindex="-1",
            )[
                tdt("Import citation dataset"),
                h.span(".ms-1", aria_hidden="true")["✓"],
            ]
            if review.citation_datasets.exists()
            else h.a(
                href=citation_upload_url,
                class_="btn btn-outline-primary",
            )[tdt("Import citation dataset")]
        )

        return [
            bc.BreadcrumbTrailForSystematicReview(review),
            h.h1[review.title],
            h.p[review.description],
            h.div(".d-flex.flex-wrap.gap-2.mb-4")[
                h.a(href="#", class_="btn btn-outline-primary")[
                    tdt("Database search")
                ],
                h.a(href="#", class_="btn btn-outline-primary")[
                    tdt("Import references")
                ],
                import_citation_dataset_link,
                h.a(
                    href=reverse("screening_criteria", args=[review.id]),
                    class_="btn btn-outline-primary",
                )[tdt("Screening criteria")],
            ],
            h.div(".d-flex.gap-2")[
                h.a(
                    href=reverse("edit_systematic_review", args=[review.id]),
                    class_="btn btn-primary",
                )[tdt("Edit systematic review")],
            ],
        ]
