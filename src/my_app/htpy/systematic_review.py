import htpy as h

from my_app.models import CitationDataset
from shortcuts import BasePageTemplate, GenericFormWithContainer
from shortcuts import breadcrumbs as bc
from shortcuts import reverse, tdt


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
    def build_stage_card(self, title, description, action):
        return h.div(".card.h-100.shadow-sm")[
            h.div(".card-body")[
                h.div(".row.align-items-center.g-3")[
                    h.div(".col-sm")[
                        h.h3(".h5.card-title.mb-1")[title],
                        h.p(".card-text.text-muted.mb-0")[description],
                    ],
                    h.div(".col-auto.d-flex.align-items-center")[action,],
                ],
            ]
        ]

    def content(self):
        review = self.context["object"]

        return [
            bc.BreadcrumbTrailForSystematicReview(review),
            h.h1[review.title],
            h.p(".text-muted.fs-5")[review.description],
            h.div(".d-grid.gap-3.mb-4")[
                h.div[
                    self.build_stage_card(
                        tdt("Database Search"),
                        tdt("Select database and define search criteria"),
                        h.a(
                            href="#",
                            class_="btn btn-secondary disabled",
                            aria_disabled="true",
                            tabindex="-1",
                        )[tdt("Coming soon")],
                    )
                ],
                h.div[
                    self._build_dataset_stage_card(review),
                ],
                h.div[
                    self.build_stage_card(
                        tdt("Title and abstract screening"),
                        tdt(
                            "Screen titles and abstracts to identify potentially eligible studies"
                        ),
                        h.a(
                            href=reverse(
                                "screening_criteria", args=[review.id]
                            ),
                            class_="btn btn-primary",
                        )[tdt("Open")],
                    )
                ],
                h.div[
                    self.build_stage_card(
                        tdt("Full text review"),
                        tdt(
                            "Review full text articles and make inclusion/exclusion decisions"
                        ),
                        h.a(
                            href="#",
                            class_="btn btn-secondary disabled",
                            aria_disabled="true",
                            tabindex="-1",
                        )[tdt("Coming soon")],
                    )
                ],
                h.div[
                    self.build_stage_card(
                        tdt("Extraction"),
                        tdt(
                            "Extract outcome and study parameters for included studies"
                        ),
                        h.a(
                            href="#",
                            class_="btn btn-secondary disabled",
                            aria_disabled="true",
                            tabindex="-1",
                        )[tdt("Coming soon")],
                    )
                ],
            ],
            h.div(".d-flex.gap-2.justify-content-end")[
                h.a(
                    href=reverse("edit_systematic_review", args=[review.id]),
                    class_="btn btn-primary",
                )[tdt("Edit systematic review")],
            ],
        ]

    def _build_dataset_stage_card(self, review):
        try:
            review.citation_dataset
        except CitationDataset.DoesNotExist:
            return self.build_stage_card(
                tdt("Import references and criteria"),
                tdt(
                    "Upload citation files, define eligibility criteria and review settings"
                ),
                h.a(
                    href=reverse("citation_upload", args=[review.id]),
                    class_="btn btn-primary",
                )[tdt("Upload dataset")],
            )

        return self.build_stage_card(
            tdt("Import references and criteria"),
            tdt(
                "Upload citation files, define eligibility criteria and review settings"
            ),
            h.a(
                href=reverse("citation_dataset_detail", args=[review.id]),
                class_="btn btn-success",
            )[f"✓ ", tdt("View dataset")],
        )
