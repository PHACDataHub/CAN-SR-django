from dataclasses import dataclass

from django import forms
from django.core.validators import FileExtensionValidator
from django.http import HttpResponse
from django.views import View

import htpy as h

from proj.htpy.form_components import ErrorSummary
from proj.htpy.modal_component import ModalComponent

from my_app.models import (
    Citation,
    Document,
    DocumentMetadata,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningResult,
    ParameterExtractionResult,
    Review,
    ScreeningResultStatus,
)
from my_app.queries import L2ScreeningStatusFetcher
from my_app.router import route
from my_app.services.preprocess_pdf import QueuePreprocessPDFService
from my_app.views.view_utils import MustAccessReviewMixin, url_with_same_params
from shortcuts import (
    BasePageTemplate,
    GenericForm,
    HtpyTemplateMixin,
    ListView,
    StandardFormMixin,
)
from shortcuts import breadcrumbs as bc
from shortcuts import (
    cached_property,
    get_object_or_404,
    reverse,
    tdt,
    transaction,
)

SCREENING_STATUS_BADGE_CLASSES = {
    ScreeningResultStatus.NOT_STARTED: "bg-secondary",
    ScreeningResultStatus.PENDING: "bg-warning text-dark",
    ScreeningResultStatus.COMPLETED: "bg-success",
    ScreeningResultStatus.ABANDONED: "bg-danger",
}

DOCUMENT_UPLOAD_BADGE_CLASSES = {
    "uploaded": "bg-success",
    "missing": "bg-secondary",
}

DOCUMENT_PROCESSING_BADGE_CLASSES = {
    DocumentMetadata.DocumentProcessingStatus.NOT_STARTED: "bg-secondary",
    DocumentMetadata.DocumentProcessingStatus.PENDING: "bg-warning text-dark",
    DocumentMetadata.DocumentProcessingStatus.COMPLETED: "bg-success",
    DocumentMetadata.DocumentProcessingStatus.FAILED: "bg-danger",
}


def get_page_number(request) -> int:
    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page_number = 1

    return max(page_number, 1)


class L2CitationUploadForm(StandardFormMixin):
    document_file = forms.FileField(
        label=tdt("PDF document"),
        validators=[FileExtensionValidator(["pdf"])],
        widget=forms.FileInput(attrs={"accept": ".pdf,application/pdf"}),
    )
    confirm_replace = forms.BooleanField(
        label=tdt(
            "I understand this will delete the existing document, metadata, and screening results before uploading the replacement."
        ),
        required=True,
    )

    def __init__(self, *args, existing_document=False, **kwargs):
        self.existing_document = existing_document
        super().__init__(*args, **kwargs)

        if not self.existing_document:
            self.fields.pop("confirm_replace", None)


def _badge(label, class_name, badge_id=None):
    attrs = {
        "class_": f"badge rounded-pill {class_name}",
    }
    if badge_id is not None:
        attrs["id"] = badge_id

    return h.span(**attrs)[label]


def _document_upload_badge(citation_row: Citation):
    if citation_row.document is None:
        return _badge(
            tdt("Not uploaded"),
            DOCUMENT_UPLOAD_BADGE_CLASSES["missing"],
        )

    return _badge(
        tdt("Uploaded"),
        DOCUMENT_UPLOAD_BADGE_CLASSES["uploaded"],
    )


def _document_processing_badge(citation_row: Citation):
    document = citation_row.document
    if document is None:
        return None

    metadata = getattr(document, "document_metadata", None)
    if metadata is None:
        status = DocumentMetadata.DocumentProcessingStatus.NOT_STARTED
    else:
        status = metadata.status

    return _badge(
        DocumentMetadata.DocumentProcessingStatus(status).label,
        DOCUMENT_PROCESSING_BADGE_CLASSES[status],
    )


def _l2_screening_badge(citation_row: Citation, status_fetcher):
    status = status_fetcher.get(citation_row.id)
    return _badge(
        status.label,
        SCREENING_STATUS_BADGE_CLASSES[status],
        badge_id=f"l2-screening-row-status-{citation_row.id}",
    )


def get_l2_pdf_detail_url(review: Review, citation_row: Citation):
    return reverse("screen_l2_row_details", args=[review.id, citation_row.id])


def get_l2_pdf_upload_url(review: Review, citation_row: Citation):
    return reverse("screen_l2_row_upload", args=[review.id, citation_row.id])


def render_l2_pdf_modal_button(
    citation_row: Citation,
    review: Review,
):
    return h.button(
        ".btn.btn-outline-primary.btn-sm",
        type="button",
        hx_get=get_l2_pdf_upload_url(review, citation_row),
        hx_target="#modal-slot",
        hx_swap="innerHTML",
    )[tdt("Re-upload") if citation_row.document is not None else tdt("Upload")]


def render_l2_pdf_detail_link(citation_row: Citation, review: Review):
    return h.a(
        ".btn.btn-outline-secondary.btn-sm",
        href=get_l2_pdf_detail_url(review, citation_row),
    )[tdt("View")]


def CitationRowDisplay(citation_row: Citation, review: Review, status_fetcher):
    row_id = f"l2-screening-row-{citation_row.id}"

    document_processing_badge = _document_processing_badge(citation_row)

    return h.div(
        ".list-group-item.citation-item.position-relative.pb-4",
        id=row_id,
    )[
        h.div(".d-flex.justify-content-between.align-items-start.gap-3")[
            h.div(".flex-grow-1")[
                h.div(".fw-semibold")[
                    citation_row.title or tdt("Untitled citation")
                ],
                (
                    h.div(".text-muted.small.mt-1")[citation_row.abstract]
                    if citation_row.abstract
                    else None
                ),
                h.div(".d-flex.flex-wrap.gap-2.mt-2.small")[
                    h.div[
                        h.span(".text-muted.me-1")[tdt("Document")],
                        _document_upload_badge(citation_row),
                    ],
                    (
                        h.div[
                            h.span(".text-muted.me-1")[tdt("Processed")],
                            document_processing_badge,
                        ]
                        if document_processing_badge is not None
                        else None
                    ),
                    h.div[
                        h.span(".text-muted.me-1")[tdt("L2 screening")],
                        _l2_screening_badge(citation_row, status_fetcher),
                    ],
                ],
            ],
            h.div(".d-flex.flex-column.align-items-end.gap-2")[
                render_l2_pdf_detail_link(citation_row, review),
                render_l2_pdf_modal_button(citation_row, review),
            ],
        ],
    ]


@dataclass
class L2ScreeningComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse("screening_l2_component", args=[self.review.id])

    @property
    def shell_url(self):
        return reverse("screening_l2", args=[self.review.id])

    @property
    def page_number(self):
        return self.page_obj.number

    @cached_property
    def citation_rows(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__document_metadata")
            .order_by("order")
        )

    @cached_property
    def page_rows(self):
        return list(self.page_obj.object_list)

    @cached_property
    def page_row_ids(self):
        return [row.id for row in self.page_rows]

    @cached_property
    def screening_questions(self):
        return list(L2ScreeningQuestion.objects.filter(review=self.review))

    @cached_property
    def total_citations(self):
        return self.citation_rows.count()

    @cached_property
    def uploaded_citations(self):
        return (
            Citation.objects.filter(
                dataset__review=self.review,
                document__isnull=False,
            )
            .values_list("id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def processed_citations(self):
        return (
            Citation.objects.filter(
                dataset__review=self.review,
                document__document_metadata__status=DocumentMetadata.DocumentProcessingStatus.COMPLETED,
            )
            .values_list("id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def screened_citations(self):
        return (
            L2ScreeningResult.objects.filter(
                citation__dataset__review=self.review
            )
            .values_list("citation_id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def status_fetcher(self):
        fetcher = L2ScreeningStatusFetcher.get_instance()
        fetcher.prefetch_keys(self.page_row_ids)
        return fetcher

    def render(self):
        return h.div(
            id="l2-screening-component",
            hx_target="this",
            hx_get=self.page_url(self.page_number, self.component_url),
            hx_trigger="click from:#refresh-button, citations-update from:body",
            hx_swap="outerHTML",
            hx_disabled_elt="#refresh-button",
        )[
            h.div(".row.g-4")[
                h.div(".col-lg-5")[self.render_progress_panel()],
                h.div(".col-lg-7")[self.render_citations_panel()],
            ]
        ]

    def render_progress_panel(self):
        if self.total_citations > 0:
            progress_percent = int(
                (self.screened_citations / self.total_citations) * 100
            )
        else:
            progress_percent = 0

        return h.section(
            id="l2-screening-progress-panel",
            class_="border rounded p-3 bg-body-tertiary",
        )[
            h.h2(".h5.mb-3")[tdt("Progress")],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Total citations")],
                h.span(".fw-semibold")[str(self.total_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Uploaded documents")],
                h.span(".fw-semibold")[str(self.uploaded_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Processed documents")],
                h.span(".fw-semibold")[str(self.processed_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Screened so far")],
                h.span(".fw-semibold")[str(self.screened_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.span[tdt("Screening questions")],
                h.span(".fw-semibold")[str(len(self.screening_questions))],
            ],
            h.div(".progress", role="progressbar")[
                h.div(
                    ".progress-bar",
                    style=f"width: {progress_percent}%",
                    aria_valuenow=str(progress_percent),
                    aria_valuemin="0",
                    aria_valuemax="100",
                )[f"{progress_percent}%"],
            ],
        ]

    def render_citations_panel(self):
        if self.page_rows:
            rows = [
                CitationRowDisplay(row, self.review, self.status_fetcher)
                for row in self.page_rows
            ]
        else:
            rows = [h.p(".text-muted.mb-0")[tdt("No citations on this page.")]]

        return h.section(".border.rounded.p-3")[
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.h2(".h5.mb-0")[tdt("Citations")],
                h.div(".text-muted.small")[
                    tdt("Page"),
                    " ",
                    str(self.page_number),
                ],
            ],
            self.render_pagination_controls(),
            h.div(".list-group")[rows],
        ]

    def render_pagination_controls(self):
        common_button_attrs = {
            "hx_target": "#l2-screening-component",
            "hx_swap": "outerHTML",
            "hx_disabled_elt": "this",
            "type": "button",
            "class": "btn btn-outline-primary btn-sm",
        }
        previous_button = h.button(
            hx_get=(
                self.page_url(
                    self.page_obj.previous_page_number(), self.component_url
                )
                if self.page_obj.has_previous()
                else None
            ),
            disabled=not self.page_obj.has_previous(),
            **common_button_attrs,
        )[tdt("Previous")]

        next_button = h.button(
            hx_get=(
                self.page_url(
                    self.page_obj.next_page_number(), self.component_url
                )
                if self.page_obj.has_next()
                else None
            ),
            disabled=not self.page_obj.has_next(),
            **common_button_attrs,
        )[tdt("Next")]

        return h.div(
            ".d-flex.justify-content-between.align-items-center.mb-3"
        )[
            h.div(".small.text-muted")[
                tdt("Page"),
                " ",
                str(self.page_number),
                " ",
                tdt("of"),
                " ",
                str(self.page_obj.paginator.num_pages),
            ],
            h.div(".btn-group")[
                previous_button,
                next_button,
            ],
        ]

    def page_url(self, page_number, path):
        return url_with_same_params(
            self.request,
            path=path,
            page=page_number,
        )


class L2ScreeningPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["review"]
        page_obj = self.context["page_obj"]
        component = L2ScreeningComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=tdt("L2 Screening")),
            ],
            h.h1[tdt("L2 Screening")],
            h.div(".mb-3")[
                h.button(
                    "#refresh-button.btn.btn-outline-secondary",
                    type="button",
                )[tdt("Refresh")],
            ],
            component.render(),
        ]


class L2ScreeningBaseView(MustAccessReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__document_metadata")
            .order_by("order")
        )


@route("/reviews/<int:review_id>/screening_l2/", name="screening_l2")
class ScreeningL2PageView(L2ScreeningBaseView, HtpyTemplateMixin):
    template_component = L2ScreeningPageTemplate


@route(
    "/reviews/<int:review_id>/screening_l2/component/",
    name="screening_l2_component",
)
class ScreeningL2ComponentView(L2ScreeningBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = L2ScreeningComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        new_page_url = reverse("screening_l2", args=[self.review.id])
        response_headers = {
            "HX-Push-Url": url_with_same_params(
                self.request,
                path=new_page_url,
                page=page_obj.number,
            )
        }

        return HttpResponse(
            str(component.render()),
            headers=response_headers,
            **response_kwargs,
        )


class L2ScreeningDocumentUploadViewMixin(MustAccessReviewMixin):
    @cached_property
    def citation_row(self):
        return get_object_or_404(
            Citation,
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

    @cached_property
    def existing_document(self):
        return self.citation_row.document

    @cached_property
    def form(self):
        return L2CitationUploadForm(
            self.request.POST or None,
            self.request.FILES or None,
            existing_document=self.existing_document is not None,
        )

    @property
    def modal_id(self):
        return f"l2-screening-upload-modal-{self.citation_row.id}"

    @property
    def form_id(self):
        return f"l2-screening-upload-form-{self.citation_row.id}"

    def render_modal(self):
        title = (
            tdt("Replace document")
            if self.existing_document is not None
            else tdt("Upload document")
        )

        footer = h.fragment[
            h.button(
                {
                    "type": "button",
                    "class": "btn btn-secondary",
                    "data-modal-close": True,
                }
            )[tdt("Cancel")],
        ]

        form_body = self.render_form_body()

        return ModalComponent(
            title=title,
            modal_id=self.modal_id,
            footer=footer,
        )[form_body]

    def render_form_body(self):
        form_content = h.form(
            id=self.form_id,
            method="post",
            enctype="multipart/form-data",
            novalidate=True,
            hx_post=reverse(
                "screen_l2_row_upload",
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target="#modal-slot",
            hx_swap="innerHTML",
            hx_encoding="multipart/form-data",
        )[
            ErrorSummary([self.form]),
            GenericForm(self.form),
            h.div(".mt-3.text-end")[
                h.button(
                    ".btn.btn-primary",
                    type="submit",
                    **{"hx-disabled-elt": "this"},
                )[
                    (
                        tdt("Replace document")
                        if self.existing_document is not None
                        else tdt("Upload document")
                    )
                ]
            ],
        ]

        if self.existing_document is None:
            return form_content

        return h.details(".border.border-danger.rounded.p-3")[
            h.summary(".fw-semibold.text-danger")[tdt("Danger zone"),],
            h.p(".text-danger.small.mb-3")[
                tdt(
                    "Replacing this document will delete the existing document, metadata, and screening results before the new file is uploaded."
                )
            ],
            form_content,
        ]

    def delete_existing_content(self):
        L1ScreeningResult.objects.filter(citation=self.citation_row).delete()
        L2ScreeningResult.objects.filter(citation=self.citation_row).delete()
        ParameterExtractionResult.objects.filter(
            citation=self.citation_row
        ).delete()

        existing_document = self.existing_document
        if existing_document is not None:
            existing_document.delete()

    def attach_new_document(self):
        document = Document.objects.create(
            file=self.form.cleaned_data["document_file"]
        )
        self.citation_row.document = document
        self.citation_row.save(update_fields=["document"])
        QueuePreprocessPDFService(document=document).perform()

    def form_valid(self):
        with transaction.atomic():
            self.delete_existing_content()
            self.attach_new_document()

        response = HttpResponse("")
        response["HX-Trigger"] = "citations-update"
        response["HX-Trigger-After-Settle"] = "modal-close"
        response["HX-Reswap"] = "none"
        return response

    def form_invalid(self):
        response = HttpResponse(self.render_modal())
        response["HX-Refocus"] = "#form-error-summary"
        return response

    def post(self, *args, **kwargs):
        if self.form.is_valid():
            return self.form_valid()

        return self.form_invalid()


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/upload/",
    name="screen_l2_row_upload",
)
class L2ScreeningRowUploadView(L2ScreeningDocumentUploadViewMixin, View):
    def get(self, *args, **kwargs):
        return HttpResponse(self.render_modal())
