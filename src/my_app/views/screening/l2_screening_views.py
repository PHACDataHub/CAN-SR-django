from django import forms
from django.core.validators import FileExtensionValidator
from django.http import FileResponse, Http404, HttpResponse, JsonResponse

from my_app.models import (
    Citation,
    Document,
    DocumentFigure,
    DocumentTable,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningResult,
    ParameterExtractionResult,
    TextExtractionResult,
)
from my_app.router import route
from my_app.services.l2_screening import DeferredL2ScreeningService
from my_app.services.process_document import QueueProcessDocumentService
from my_app.views.screening.l2_common_components import L2DocumentUploadModal
from my_app.views.screening.l2_screening_index_templating import (
    L2ScreeningComponent,
    L2ScreeningPageTemplate,
)
from my_app.views.screening.l2_screening_pdf_templating import (
    L2PdfScreeningPage,
    render_l2_screening_control,
)
from my_app.views.view_utils import MustAccessReviewMixin, url_with_same_params
from shortcuts import (
    DetailView,
    HtpyTemplateMixin,
    ListView,
    StandardFormMixin,
    View,
    cached_property,
    get_object_or_404,
    reverse,
    tdt,
    transaction,
)

from .util import can_start_l2_screening


class L2CitationUploadForm(StandardFormMixin):
    document_file = forms.FileField(
        label=tdt("PDF document"),
        validators=[FileExtensionValidator(["pdf"])],
        widget=forms.FileInput(attrs={"accept": ".pdf,application/pdf"}),
    )
    confirm_replace = forms.BooleanField(
        label=tdt(
            "I understand this will delete the existing document, text extraction result, and screening results before uploading the replacement."
        ),
        required=True,
    )

    def __init__(self, *args, existing_document=False, **kwargs):
        self.existing_document = existing_document
        super().__init__(*args, **kwargs)

        if not self.existing_document:
            self.fields.pop("confirm_replace", None)


class L2ScreeningBaseView(MustAccessReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__text_extraction_result")
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

    @cached_property
    def modal(self):
        return L2DocumentUploadModal(
            form=self.form,
            review=self.review,
            citation_row=self.citation_row,
            existing_document=self.existing_document,
        )

    def render_modal(self):
        return self.modal.render()

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
        QueueProcessDocumentService(document=document).perform()

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


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/details/",
    name="screen_l2_row_details",
)
class L2PdfScreeningView(MustAccessReviewMixin, DetailView, HtpyTemplateMixin):
    model = Citation
    pk_url_kwarg = "row_pk"
    template_component = L2PdfScreeningPage

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__text_extraction_result")
            .order_by("order")
        )


class L2PdfCitationMixin(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        try:
            return Citation.objects.select_related(
                "document", "document__text_extraction_result"
            ).get(
                pk=self.kwargs["row_pk"],
                dataset__review=self.review,
            )
        except Citation.DoesNotExist as exc:
            raise Http404 from exc

    @property
    def document(self):
        document = self.citation_row.document
        if document is None:
            raise Http404
        return document


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/process/",
    name="screen_l2_row_process",
)
class L2PdfScreeningProcessView(L2PdfCitationMixin):
    @cached_property
    def screening_questions(self):
        return list(L2ScreeningQuestion.objects.filter(review=self.review))

    def post(self, request, *args, **kwargs):
        if not can_start_l2_screening(self.citation_row):
            return HttpResponse(
                str(
                    render_l2_screening_control(
                        self.citation_row,
                        self.review,
                    )
                ),
                status=409,
            )

        DeferredL2ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
            overwrite_existing=True,
        ).perform()

        return HttpResponse(
            str(render_l2_screening_control(self.citation_row, self.review))
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/pdf/",
    name="screen_l2_row_pdf",
)
class L2PdfCitationView(L2PdfCitationMixin):
    def get(self, request, *args, **kwargs):
        document_file = self.document.file
        return FileResponse(
            document_file.open("rb"),
            content_type="application/pdf",
            as_attachment=False,
            filename=document_file.name,
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/pdf-metadata/",
    name="screen_l2_row_pdf_metadata",
)
class L2PdfCitationMetadataView(L2PdfCitationMixin):
    def get(self, request, *args, **kwargs):
        text_extraction_result = getattr(
            self.document, "text_extraction_result", None
        )
        if text_extraction_result is None:
            raise Http404

        return JsonResponse(
            {
                "pages": text_extraction_result.pages,
                "highlights": self.get_highlights(text_extraction_result),
            }
        )

    def get_highlights(self, text_extraction_result):
        highlights = []
        highlights.extend(self.get_sentence_highlights(text_extraction_result))
        highlights.extend(self.get_artifact_highlights(DocumentTable, "table"))
        highlights.extend(
            self.get_artifact_highlights(DocumentFigure, "figure")
        )
        return highlights

    def get_sentence_highlights(self, text_extraction_result):
        sentence_texts = text_extraction_result.get_sentence_list()
        evidence_indices = self.get_evidence_indices("evidence_sentences")
        sentence_coordinates = [
            coordinate
            for coordinate in text_extraction_result.coordinates
            if coordinate.get("type") == "s"
        ]

        highlights = []
        for sentence_index in evidence_indices:
            if sentence_index >= len(sentence_texts):
                continue

            sentence_text = sentence_texts[sentence_index]
            highlights.extend(
                {
                    **coordinate,
                    "sentence_index": sentence_index,
                    "evidence_type": "sentence",
                    "evidence_index": sentence_index,
                }
                for coordinate in sentence_coordinates
                if coordinate.get("text") == sentence_text
            )

        return highlights

    def get_artifact_highlights(self, artifact_model, evidence_type):
        evidence_indices = self.get_evidence_indices(
            f"evidence_{evidence_type}s"
        )
        artifacts = artifact_model.objects.filter(
            document=self.document,
            index__in=evidence_indices,
        )

        return [
            {
                **coordinate,
                "evidence_type": evidence_type,
                "evidence_index": artifact.index,
            }
            for artifact in artifacts
            for coordinate in artifact.bounding_box
        ]

    def get_evidence_indices(self, evidence_field):
        results = L2ScreeningResult.objects.filter(
            citation=self.citation_row
        ).order_by("question_id")
        evidence_indices = [
            evidence_index
            for result in results
            for evidence_index in getattr(result, evidence_field)
            if isinstance(evidence_index, int) and evidence_index >= 0
        ]
        return list(dict.fromkeys(evidence_indices))
