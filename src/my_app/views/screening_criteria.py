import abc
import uuid
from urllib.parse import urlencode

import htpy as h
from django import forms
from django.http import HttpResponseBadRequest
from django.views.generic import TemplateView

from my_app.models import (
    CitationDataset,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    ParameterQuestion,
    ParameterQuestionOption,
    SystematicReview,
)
from my_app.router import route
from my_app.views.view_utils import MustAccessSystematicReviewMixin
from proj.htpy.form_components import ErrorSummary, InlineFormset
from proj.htpy.modal_component import ModalComponent
from shortcuts import (
    BasePageTemplate,
    GenericForm,
    HtpyComponent,
    HtpyTemplateMixin,
    HttpResponse,
    ModelForm,
    QueryDict,
    QuerySet,
    StandardFormMixin,
)
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, dataclass, reverse, tdt, tm, transaction

ChildType = L1ScreeningQuestion | L2ScreeningQuestion | ParameterQuestion
OptionType = (
    L1ScreeningQuestionOption
    | L2ScreeningQuestionOption
    | ParameterQuestionOption
)


class FormsetAdapterMeta(abc.ABCMeta):
    def __new__(cls, name, bases, attrs):
        new_cls = super().__new__(cls, name, bases, attrs)

        if abc.ABC not in bases:
            assert hasattr(new_cls, "model"), "model is required"
            assert hasattr(new_cls, "FormClass"), "FormClass is required"
            assert hasattr(new_cls, "option_model"), "option_model is required"
            assert hasattr(
                new_cls, "form_renderer"
            ), "form_renderer is required"
            assert hasattr(
                new_cls, "option_form_renderer"
            ), "option_form_renderer is required"
            assert hasattr(
                new_cls, "OptionFormClass"
            ), "OptionFormClass is required"

        return new_cls


class FormsetAdapter(abc.ABC, metaclass=FormsetAdapterMeta):
    @abc.abstractstaticmethod
    def get_edit_url(obj):
        raise NotImplementedError

    @abc.abstractstaticmethod
    def get_new_url(review):
        raise NotImplementedError

    def form_renderer(form):
        return GenericForm(form)

    @staticmethod
    def option_form_renderer(form):
        return h.div[GenericForm(form)]

    add_button_text = tdt("Add question")

    @classmethod
    def get_section_name(cls):
        return f"{cls.__name__.lower()}-section"


class L1FormsetAdapter(FormsetAdapter):
    class FormClass(ModelForm, StandardFormMixin):
        class Meta:
            model = L1ScreeningQuestion
            fields = ["question_text"]

    model = L1ScreeningQuestion
    option_model = L1ScreeningQuestionOption

    class OptionFormClass(ModelForm, StandardFormMixin):
        class Meta:
            model = L1ScreeningQuestionOption
            fields = ["option_text", "option_value"]

    @staticmethod
    def get_new_url(review):
        return reverse("add_l1_question", args=[review.pk])

    @staticmethod
    def get_edit_url(obj):
        return reverse("edit_l1_question", args=[obj.review_id, obj.pk])


class L2FormsetAdapter(FormsetAdapter):
    model = L2ScreeningQuestion

    class FormClass(ModelForm, StandardFormMixin):
        class Meta:
            model = L2ScreeningQuestion
            fields = ["question_text"]

    option_model = L2ScreeningQuestionOption

    class OptionFormClass(ModelForm, StandardFormMixin):
        class Meta:
            model = L2ScreeningQuestionOption
            fields = ["option_text", "option_value"]

    @staticmethod
    def get_new_url(review):
        return reverse("add_l2_question", args=[review.pk])

    @staticmethod
    def get_edit_url(obj):
        return reverse("edit_l2_question", args=[obj.review_id, obj.pk])


class ParameterFormsetAdapter(FormsetAdapter):
    model = ParameterQuestion

    class FormClass(ModelForm, StandardFormMixin):
        class Meta:
            model = ParameterQuestion
            fields = ["question_text"]

    option_model = ParameterQuestionOption

    class OptionFormClass(ModelForm, StandardFormMixin):
        class Meta:
            model = ParameterQuestionOption
            fields = ["param_name", "param_description"]

    @staticmethod
    def get_new_url(review):
        return reverse("add_parameter_question", args=[review.pk])

    @staticmethod
    def get_edit_url(obj):
        return reverse("edit_parameter_question", args=[obj.review_id, obj.pk])

    add_button_text = tdt("Add Parameter")


class ScreeningCriteriaPageContent(HtpyComponent):
    def __init__(self, review: SystematicReview):
        self.review = review

    @cached_property
    def dataset(self):
        try:
            return CitationDataset.objects.prefetch_related(
                "columns",
                "screening_columns",
            ).get(systematic_review=self.review)
        except CitationDataset.DoesNotExist:
            return None

    def render_screening_columns_section(self):
        dataset = self.dataset
        if dataset is None:
            return h.div[
                h.h2(".h5")[tdt("Screening columns")],
                h.p(".mb-0")[tdt("No citation dataset yet.")],
            ]

        screening_columns = list(dataset.screening_columns.order_by("id"))

        columns_content = h.ul(".list-group")[
            h.li(".list-group-item.list-group-item-secondary")[tdt("Title"),],
            h.li(".list-group-item.list-group-item-secondary")[
                tdt("Abstract"),
            ],
            *[
                h.li(".list-group-item")[column.name]
                for column in screening_columns
            ],
        ]

        header_children = [h.h2(".h5.mb-0")[tdt("Screening columns")]]
        edit_button = None
        if dataset is not None:
            edit_button = h.button(
                ".btn.btn-outline-primary.btn-sm",
                hx_get=reverse(
                    "edit_screening_columns", args=[self.review.pk]
                ),
                hx_target="#modal-slot",
                id="edit-screening-columns-button",
                hx_preserve="true",
                type="button",
            )[tm("edit")]
            header_children.append(edit_button)

        return h.div(
            id="screening-columns-section",
            hx_swap_oob="true",
        )[
            h.div(".d-flex.justify-content-between.align-items-start.mb-2")[
                header_children
            ],
            h.p(".small.text-muted.mb-0.mt-2")[
                tdt("Title and Abstract are always included")
            ],
            columns_content,
        ]

    def render_form_and_formset_section(self, adapter: type[FormsetAdapter]):
        review = self.review
        section_id = adapter.get_section_name()
        child_records = adapter.model.objects.filter(review=review)

        if child_records:
            child_content = h.ul(".list-group")[
                (
                    h.li(".list-group-item")[
                        h.div(".d-flex.justify-content-between.mb-1")[
                            h.div[child.title],
                            h.div[
                                h.button(
                                    ".btn.btn-outline-primary.btn-sm",
                                    hx_get=adapter.get_edit_url(child),
                                    hx_target="#modal-slot",
                                    # hx-preserve requires a stable ID
                                    id=f"edit-{section_id}-{child.pk}-button",
                                    hx_preserve="true",
                                )[tm("edit")]
                            ],
                        ],
                        h.div[tdt("options")],
                        h.ul(".list-group")[
                            (
                                h.li(".list-group-item")[
                                    h.div[option.title],
                                    h.div(".small.text-secondary")[
                                        option.description
                                    ],
                                ]
                                for option in child.options.all()
                            )
                        ],
                    ]
                    for child in child_records
                )
            ]
        else:
            child_content = h.p[tdt("No questions/parameters added yet.")]

        return h.fragment[
            h.div(
                id=section_id,
                tab_index=-1,
                hx_swap_oob="true",
            )[
                h.div[child_content],
            ],
            h.div(".mt-1.mb-3")[
                h.button(
                    hx_get=adapter.get_new_url(review),
                    hx_target="#modal-slot",
                    type="button",
                    class_="btn btn-primary btn-sm",
                )[adapter.add_button_text]
            ],
        ]

    def render(self):
        return [
            bc.BreadcrumbTrailForSystematicReview(self.review)[
                bc.BreadcrumbItem(label=tdt("Screening criteria"))
            ],
            h.h1[tdt("Screening criteria")],
            self.render_screening_columns_section(),
            h.h2(".h5.mb-0.mt-3")[tdt("L1 screening questions")],
            self.render_form_and_formset_section(L1FormsetAdapter),
            h.h2(".h5.mb-0.mt-3")[tdt("L2 screening questions")],
            self.render_form_and_formset_section(L2FormsetAdapter),
            h.h2(".h5.mb-0.mt-3")[tdt("Parameters")],
            self.render_form_and_formset_section(ParameterFormsetAdapter),
        ]


class ScreeningCriteriaPage(BasePageTemplate):
    def content(self):
        return ScreeningCriteriaPageContent(
            self.context["systematic_review"]
        ).render()


@route(
    "systematic-reviews/<int:pk>/screening-criteria/",
    name="screening_criteria",
)
class ScreeningCriteriaView(
    TemplateView, MustAccessSystematicReviewMixin, HtpyTemplateMixin
):
    template_component = ScreeningCriteriaPage

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["systematic_review"] = self.systematic_review
        return context


@dataclass
class ChildEditor:
    """

    Design note:

    A single Question(parameter) + its options are the unit of saving

    This helper can be composed by the add vs. edit views, for both models

    """

    adapter: FormsetAdapter
    child: ChildType
    data: QueryDict | None = None

    @property
    def post_url(self):
        if self.child.pk is None:
            url = self.adapter.get_new_url(self.child.review)
        else:
            url = self.adapter.get_edit_url(self.child)

        return url

    @cached_property
    def child_form(self):
        return self.adapter.FormClass(
            self.data,
            instance=self.child,
        )

    @property
    def form_id(self):
        return self.adapter.__name__

    @cached_property
    def option_formset(self):

        if self.child.pk and self.child.options.exists():
            extra = 0
        else:
            extra = 1

        FormSetCls = forms.models.inlineformset_factory(
            parent_model=self.adapter.model,
            model=self.adapter.option_model,
            form=self.adapter.OptionFormClass,
            extra=extra,
            can_delete=True,
        )

        parent_instance = self.child
        return FormSetCls(
            self.data, instance=parent_instance, prefix="options"
        )

    def is_valid(self):
        return self.child_form.is_valid() and self.option_formset.is_valid()

    def save(self):
        self.is_valid()  # to populate cleaned_data and errors
        with transaction.atomic():
            child = self.child_form.save()
            formset = self.option_formset

            formset.save()

        return child

    def render_form(self):

        post_url = self.post_url

        error_summary = None
        if self.data is not None:
            error_summary = ErrorSummary(
                [self.child_form, *self.option_formset.forms]
            )

        return h.form(
            hx_post=post_url,
            hx_target="this",
            hx_swap="outerHTML",
            hx_select=f"#{self.form_id}",
            class_="mb-4 border p-3 rounded",
            id=self.form_id,
        )[
            error_summary,
            self.adapter.form_renderer(self.child_form),
            InlineFormset(
                self.option_formset,
                add_button_text=tdt("Add option"),
                form_renderer=self.adapter.option_form_renderer,
                can_add=True,
                aria_list_label=tdt("options"),
            ),
        ]

    def render_modal(self):
        body = self.render_form()

        footer = h.fragment[
            h.button(
                {
                    "type": "button",
                    "class": "btn btn-secondary",
                    "data-modal-close": True,
                }
            )[tm("cancel")],
            h.button(
                {
                    "type": "submit",
                    "class": "btn btn-primary",
                    "hx-disabled-elt": "this",
                    "form": self.form_id,
                }
            )[tm("save")],
        ]

        return ModalComponent(
            title=tdt("Edit question/parameter"),
            footer=footer,
            modal_id=f"{self.form_id}-modal",
        )[body]


class ChildEditorModalFormView(MustAccessSystematicReviewMixin):
    adapter: type[FormsetAdapter]

    editor: ChildEditor

    def get(self, *args, **kwargs):
        return HttpResponse(self.editor.render_modal())

    def form_valid(self):
        # re-render the entire parent page
        # hx-swap-oob will take care of swapping updated data
        content = ScreeningCriteriaPageContent(self.systematic_review).render()
        resp = HttpResponse(content)
        resp["HX-Trigger-After-Settle"] = "modal-close"
        resp["Hx-Reswap"] = "none"

        return resp

    def form_invalid(self):
        resp = HttpResponse(self.editor.render_modal())
        resp["HX-Refocus"] = f"#{self.editor.form_id}-error-summary"
        return resp

    def post(self, *args, **kwargs):
        if self.editor.is_valid():
            self.editor.save()
            return self.form_valid()
        else:
            return self.form_invalid()


class ChildEditorCreateView(ChildEditorModalFormView):

    @cached_property
    def editor(self):
        child = self.adapter.model(review=self.systematic_review)
        editor = ChildEditor(
            child=child,
            data=self.request.POST or None,
            adapter=self.adapter,
        )
        return editor


class ChildEditorEditView(ChildEditorModalFormView):

    @cached_property
    def editor(self):
        question_id = self.kwargs["question_pk"]

        try:
            question = self.adapter.model.objects.get(pk=question_id)
        except self.adapter.model.DoesNotExist:
            raise ValueError("Invalid question ID")

        editor = ChildEditor(
            child=question,
            adapter=self.adapter,
            data=self.request.POST or None,
        )
        return editor


@route(
    "systematic_reviews/<int:pk>/add_l1_screening_question",
    name="add_l1_question",
)
class AddL1ScreeningQuestionView(ChildEditorCreateView):
    adapter = L1FormsetAdapter


@route(
    "systematic_reviews/<int:pk>/l1_screening_questions/<int:question_pk>/edit",
    name="edit_l1_question",
)
class EditL1ScreeningQuestionView(ChildEditorEditView):
    adapter = L1FormsetAdapter


@route(
    "systematic_reviews/<int:pk>/l2_screening_questions/add/",
    name="add_l2_question",
)
class AddL2ScreeningQuestionView(ChildEditorCreateView):
    adapter = L2FormsetAdapter


@route(
    "systematic_reviews/<int:pk>/l2_screening_questions/<int:question_pk>/edit",
    name="edit_l2_question",
)
class EditL2ScreeningQuestionView(ChildEditorEditView):
    adapter = L2FormsetAdapter


@route(
    "systematic_reviews/<int:pk>/parameters/add/",
    name="add_parameter_question",
)
class AddParameterQuestionView(ChildEditorCreateView):
    adapter = ParameterFormsetAdapter


@route(
    "systematic_reviews/<int:pk>/parameters/<int:question_pk>/edit",
    name="edit_parameter_question",
)
class EditParameterQuestionView(ChildEditorEditView):
    adapter = ParameterFormsetAdapter


class ScreeningColumnsSelectionForm(ModelForm, StandardFormMixin):
    class Meta:
        model = CitationDataset
        fields = ["screening_columns"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["screening_columns"]
        field.queryset = self.instance.columns.all()
        field.required = False


@route(
    "systematic_reviews/<int:pk>/edit-screening-columns/",
    name="edit_screening_columns",
)
class EditScreeningColumnsModal(MustAccessSystematicReviewMixin):
    @cached_property
    def dataset(self):
        try:
            return self.systematic_review.citation_dataset
        except CitationDataset.DoesNotExist:
            return None

    @cached_property
    def form(self):
        return ScreeningColumnsSelectionForm(
            self.request.POST or None,
            instance=self.dataset,
        )

    def _render_page(self):
        return ScreeningCriteriaPageContent(self.systematic_review).render()

    def _render_modal(self):
        footer = h.fragment[
            h.button(
                {
                    "type": "button",
                    "class": "btn btn-secondary",
                    "data-modal-close": True,
                }
            )[tm("cancel")],
            h.button(
                {
                    "type": "submit",
                    "class": "btn btn-primary",
                    "hx-disabled-elt": "this",
                    "form": "screening-columns-form",
                }
            )[tm("save")],
        ]

        return ModalComponent(
            title=tdt("Edit screening columns"),
            modal_id="screening-columns-modal",
            footer=footer,
        )[
            h.p(".small.text-muted.mb-0")[
                tdt("Title and Abstract are always included")
            ],
            h.form(
                hx_post=reverse(
                    "edit_screening_columns", args=[self.systematic_review.pk]
                ),
                hx_target="this",
                hx_swap="outerHTML",
                hx_select="#screening-columns-form",
                id="screening-columns-form",
            )[
                GenericForm(self.form),
            ],
        ]

    def get(self, *args, **kwargs):
        if self.dataset is None:
            return HttpResponseBadRequest(tdt("Dataset not found."))

        return HttpResponse(self._render_modal())

    def post(self, *args, **kwargs):
        if self.dataset is None:
            return HttpResponseBadRequest(tdt("Dataset not found."))

        if self.form.is_valid():
            return self.form_valid()
        return self.form_invalid()

    def form_valid(self):
        self.form.save()

        resp = HttpResponse(self._render_page())
        resp["HX-Trigger-After-Settle"] = "modal-close"
        resp["Hx-Reswap"] = "none"
        return resp

    def form_invalid(self):
        resp = HttpResponse(self._render_modal())
        resp["HX-Refocus"] = "#screening-columns-form"
        return resp
