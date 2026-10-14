from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

import htpy as h

from my_app.router import route
from my_app.services.create_criteria_from_yaml import CreateCriteriaFromYaml
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    BasePageTemplate,
    FormView,
    GenericForm,
    HtpyTemplateMixin,
    StandardFormMixin,
)
from shortcuts import breadcrumbs as bc
from shortcuts import reverse, tdt


class CriteriaUploadForm(StandardFormMixin):
    yaml_file = forms.FileField(
        label=tdt("Criteria YAML file"),
        validators=[FileExtensionValidator(["yaml", "yml"])],
        widget=forms.FileInput(attrs={"accept": ".yaml,.yml"}),
    )
    confirm_delete = forms.BooleanField(
        label=tdt(
            "I agree that submitting this YAML file will permanently delete all existing criteria and their associated results for this review."
        ),
        required=True,
    )


class CriteriaUploadPage(BasePageTemplate):
    def title(self):
        return tdt("Upload criteria YAML")

    def content(self):
        review = self.context["review"]
        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("Screening criteria"),
                    href=reverse("screening_criteria", args=[review.pk]),
                ),
                bc.BreadcrumbItem(label=self.title()),
            ],
            h.h1[self.title()],
            h.form(
                method="post", enctype="multipart/form-data", novalidate=True
            )[
                GenericForm(self.context["form"]),
                h.button(".btn.btn-primary", type="submit")[
                    tdt("Upload and replace criteria")
                ],
            ],
        ]


@route("reviews/<int:review_id>/criteria-upload/", name="criteria_upload")
class CriteriaUploadView(MustAccessReviewMixin, FormView, HtpyTemplateMixin):
    form_class = CriteriaUploadForm
    template_component = CriteriaUploadPage

    def form_valid(self, form):
        try:
            yaml_string = (
                form.cleaned_data["yaml_file"].read().decode("utf-8-sig")
            )
            CreateCriteriaFromYaml(self.review, yaml_string).run()
        except UnicodeDecodeError:
            form.add_error(
                "yaml_file", tdt("Upload a UTF-8 encoded YAML file.")
            )
            return self.form_invalid(form)
        except ValidationError as error:
            form.add_error("yaml_file", error)
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("screening_criteria", args=[self.review.pk])
