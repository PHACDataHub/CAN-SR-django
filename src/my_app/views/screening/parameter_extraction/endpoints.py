from django import forms
from django.http import HttpResponse

import htpy as h

from my_app.models import (
    Parameter,
    ParameterExtractionResult,
    ParameterHumanAnswer,
)
from my_app.router import route
from my_app.services.parameter_extraction import (
    EnqueueParameterExtractionService,
)
from my_app.views.screening.document_util_components import (
    DocumentCitationMixin,
    PdfCitationMetadataView,
)
from my_app.views.screening.human_answers import (
    HumanAnswerFormView,
    ScreeningHumanAnswerViewMixin,
    ValidateAIAnswerView,
)
from my_app.views.screening.parameter_extraction.detail import (
    render_parameter_extraction_control,
)
from my_app.views.screening.parameter_extraction.list import (
    render_parameter_human_review_control,
)
from my_app.views.screening.util import can_start_parameter_extraction
from shortcuts import StandardFormMixin, cached_property, tdt


class ParameterExtractionHumanAnswerForm(
    forms.ModelForm,
    StandardFormMixin,
):
    found = forms.TypedChoiceField(
        label=tdt("Found"),
        choices=((True, tdt("Yes")), (False, tdt("No"))),
        coerce=lambda value: value == "True",
        widget=forms.RadioSelect,
    )

    class Meta:
        model = ParameterHumanAnswer
        fields = ["found", "value", "selected_option", "notes"]
        labels = {
            "found": tdt("Found"),
            "value": tdt("Value"),
            "selected_option": tdt("Value"),
            "notes": tdt("Notes"),
        }

    def __init__(self, *args, question, **kwargs):
        super().__init__(*args, **kwargs)
        self.question = question
        if question.option_type == Parameter.OptionType.SELECT:
            self.fields.pop("value")
            self.fields["selected_option"].queryset = question.options.filter(
                deletion_time__isnull=True
            )
        else:
            self.fields.pop("selected_option")

    def clean_value(self):
        return self.cleaned_data["value"] or None

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("found")
            and self.question.option_type == Parameter.OptionType.SELECT
            and not cleaned_data.get("selected_option")
        ):
            self.add_error(
                "selected_option",
                tdt("Select an option when the parameter was found."),
            )
        return cleaned_data

    def save(self, commit=True):
        answer = super().save(commit=False)
        if self.question.option_type == Parameter.OptionType.SELECT:
            answer.value = None
        else:
            answer.selected_option = None
        if commit:
            answer.save()
        return answer


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/process/",
    name="parameter_extraction_citation_process_extraction",
)
class ParameterExtractionProcessView(DocumentCitationMixin):
    @cached_property
    def parameters(self):
        return list(Parameter.active_objects.filter(review=self.review))

    def post(self, request, *args, **kwargs):
        if not can_start_parameter_extraction(self.citation_row):
            return HttpResponse(
                str(
                    render_parameter_extraction_control(
                        self.citation_row,
                        self.review,
                    )
                ),
                status=409,
            )

        EnqueueParameterExtractionService(
            rows=[self.citation_row],
            questions=self.parameters,
            overwrite_existing=True,
        ).perform()

        return HttpResponse(
            str(
                render_parameter_extraction_control(
                    self.citation_row,
                    self.review,
                )
            )
        )


class ParameterExtractionHumanReviewMixin(ScreeningHumanAnswerViewMixin):
    result_model = ParameterExtractionResult
    answer_model = ParameterHumanAnswer
    form_class = ParameterExtractionHumanAnswerForm
    prefix = "parameter-extraction"
    route_name = "parameter_extraction_citation_human_answer"
    render_control_component = staticmethod(
        render_parameter_human_review_control
    )
    result_select_related = (
        "citation",
        "question",
        "question__review",
        "selected_option",
    )
    modal_title = tdt("Your parameter answer")

    def can_validate(self):
        return True

    def validated_answer_values(self):
        return {
            "found": self.result.found,
            "value": self.result.value,
            "selected_option": self.result.selected_option,
        }

    def human_answer_form_kwargs(self):
        return {"question": self.result.question}


@route(
    "/reviews/<int:review_id>/parameter_extraction/results/<int:result_pk>/validate-ai-answer/",
    name="parameter_extraction_citation_validate_ai_answer",
)
class ParameterExtractionValidateAiAnswerView(
    ParameterExtractionHumanReviewMixin,
    ValidateAIAnswerView,
):
    pass


@route(
    "/reviews/<int:review_id>/parameter_extraction/results/<int:result_pk>/human-answer/",
    name="parameter_extraction_citation_human_answer",
)
class ParameterExtractionHumanAnswerView(
    ParameterExtractionHumanReviewMixin,
    HumanAnswerFormView,
):
    pass


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/pdf-metadata/",
    name="parameter_extraction_citation_pdf_metadata",
)
class ParameterExtractionPdfCitationMetadataView(PdfCitationMetadataView):
    result_model = ParameterExtractionResult
