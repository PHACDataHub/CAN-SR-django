import htpy as h

from my_app.models import CitationDataset
from shortcuts import BasePageTemplate, GenericFormWithContainer
from shortcuts import breadcrumbs as bc
from shortcuts import reverse, tdt


class ReviewListPage(BasePageTemplate):
    def content(self):
        reviews = self.context["object_list"]

        return [
            bc.BreadcrumbTrail()[
                bc.BreadcrumbItem(label=tdt("Systematic Reviews"))
            ],
            h.h1[tdt("Systematic review list")],
            h.div(".mb-3")[
                h.a(
                    href=reverse("create_review"),
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
                                    "review_detail",
                                    args=[review.id],
                                )
                            )[review.title]
                        ]
                        for review in reviews
                    ]
                ]
            ),
        ]


class ReviewCreatePage(BasePageTemplate):

    def content(self):
        return [
            bc.BreadcrumbTrail()[
                bc.ListReviewsItem(),
                bc.BreadcrumbItem(label=tdt("Create systematic review")),
            ],
            h.h1[tdt("Create systematic review")],
            GenericFormWithContainer(
                self.context["form"],
            ),
        ]


class ReviewEditPage(BasePageTemplate):
    def content(self):
        review = self.context.get("object")
        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=tdt("Edit"))
            ],
            h.h1[tdt("Edit review")],
            GenericFormWithContainer(
                self.context["form"],
            ),
        ]


class ReviewDetailPage(BasePageTemplate):
    def build_stage_card(self, title, description, action):
        return h.div(".card.h-100.shadow-sm")[
            h.div(".card-body")[
                h.div(".row.align-items-center.g-3")[
                    h.div(".col-sm")[
                        h.h3(".h5.card-title.mb-1")[title],
                        h.div(".card-text.text-muted.mb-0")[description],
                    ],
                    h.div(".col-auto.d-flex.align-items-center")[action,],
                ],
            ]
        ]

    def content(self):
        review = self.context["object"]
        dataset = getattr(review, "citation_dataset", None)

        screening_text = tdt(
            "Select which columns to include, identify L1/L2 criteria, and define parameters for extraction"
        )
        if dataset:
            screening_criteria_card = self.build_stage_card(
                tdt("Configure screening criteria"),
                screening_text,
                h.a(
                    href=reverse("screening_criteria", args=[review.id]),
                    class_="btn btn-primary",
                )[tdt("Open")],
            )
        else:
            screening_criteria_card = self.build_stage_card(
                tdt("Configure screening criteria"),
                h.div[
                    screening_text,
                    h.p(".fw-bold")[
                        tdt(
                            " You need to upload a dataset before you can configure screening criteria."
                        )
                    ],
                ],
                h.a(
                    href="#",
                    class_="btn btn-secondary disabled",
                    aria_disabled="true",
                    tabindex="-1",
                )[tdt("Open")],
            )

        return [
            bc.BreadcrumbTrailForReview(review),
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
                h.div[self._build_dataset_stage_card(review),],
                h.div[screening_criteria_card],
                h.div[
                    self.build_stage_card(
                        tdt("Title and abstract screening"),
                        tdt(
                            "Screen titles and abstracts to identify potentially eligible studies"
                        ),
                        h.a(
                            href=reverse("screening_l1", args=[review.id]),
                            class_="btn btn-primary",
                        )[tdt("L1 screening")],
                    )
                ],
                h.div[
                    self.build_stage_card(
                        tdt("Full text review"),
                        tdt(
                            "Review full text articles and make inclusion/exclusion decisions"
                        ),
                        h.a(
                            href=reverse("screening_l2", args=[review.id]),
                            class_="btn btn-primary",
                        )[tdt("L2 screening")],
                    )
                ],
                h.div[
                    self.build_stage_card(
                        tdt("Extraction"),
                        tdt(
                            "Extract outcome and study parameters for included studies"
                        ),
                        h.a(
                            href=reverse(
                                "parameter_extraction",
                                args=[review.id],
                            ),
                            class_="btn btn-primary",
                        )[tdt("Parameter extraction")],
                    )
                ],
            ],
            h.div(".d-flex.gap-2.justify-content-end")[
                h.a(
                    href=reverse("edit_review", args=[review.id]),
                    class_="btn btn-primary",
                )[tdt("Edit review")],
            ],
        ]

    def _build_dataset_stage_card(self, review):
        try:
            review.citation_dataset
        except CitationDataset.DoesNotExist:
            return self.build_stage_card(
                tdt("Import references and criteria"),
                tdt("Upload citation files"),
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
