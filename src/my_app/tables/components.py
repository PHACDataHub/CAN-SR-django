import htpy as h

from shortcuts import reverse, tdt


def TableNavigation(review):
    return h.details(".mb-3")[
        h.summary[tdt("More tables")],
        h.nav(".mt-2", aria_label=tdt("Review tables"))[
            h.ul(".list-inline")[
                h.li(".list-inline-item")[
                    h.a(href=reverse("citation_table", args=[review.pk]))[
                        tdt("Citations")
                    ]
                ],
                h.li(".list-inline-item")[
                    h.a(href=reverse("l1_ai_answer_table", args=[review.pk]))[
                        tdt("L1 AI answers")
                    ]
                ],
                h.li(".list-inline-item")[
                    h.a(href=reverse("l2_ai_answer_table", args=[review.pk]))[
                        tdt("L2 AI answers")
                    ]
                ],
                h.li(".list-inline-item")[
                    h.a(
                        href=reverse("l1_human_answer_table", args=[review.pk])
                    )[tdt("L1 human answers")]
                ],
                h.li(".list-inline-item")[
                    h.a(
                        href=reverse("l2_human_answer_table", args=[review.pk])
                    )[tdt("L2 human answers")]
                ],
            ]
        ],
    ]
