from django.http import FileResponse, Http404, JsonResponse

from my_app.models import Citation, DocumentFigure, DocumentTable
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import View, cached_property


class PdfCitationMixin(MustAccessReviewMixin, View):
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


class PdfCitationFileView(PdfCitationMixin):
    def get(self, request, *args, **kwargs):
        document_file = self.document.file
        return FileResponse(
            document_file.open("rb"),
            content_type="application/pdf",
            as_attachment=False,
            filename=document_file.name,
        )


class PdfCitationMetadataView(PdfCitationMixin):
    result_model = None

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
        results = self.result_model.objects.filter(
            citation=self.citation_row
        ).order_by("question_id")
        evidence_indices = [
            evidence_index
            for result in results
            for evidence_index in getattr(result, evidence_field)
            if isinstance(evidence_index, int) and evidence_index >= 0
        ]
        return list(dict.fromkeys(evidence_indices))
