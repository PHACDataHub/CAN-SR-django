import abc
import uuid
from urllib.parse import urlencode

import htpy as h
from django import forms
from django.views.generic import TemplateView

from my_app.models import (
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
from proj.htpy.form_components import InlineFormset
from shortcuts import (
    BasePageTemplate,
    GenericForm,
    HtpyTemplateMixin,
    HttpResponse,
    ModelForm,
    QueryDict,
    QuerySet,
    StandardFormMixin,
)
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, dataclass, reverse, tdt, transaction

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
    @abc.abstractmethod
    def get_edit_url(self, obj):
        raise NotImplementedError

    @abc.abstractstaticmethod
    def get_new_url(review):
        raise NotImplementedError

    def form_renderer(form):
        return GenericForm(form)

    @staticmethod
    def option_form_renderer(form):
        return GenericForm(form)

    add_button_text = tdt("Add option")


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
        return reverse("edit_l1_question", args=[obj.pk])


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
        return reverse("edit_l2_question", args=[obj.pk])


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
        return reverse("edit_parameter_question", args=[obj.pk])


class ScreeningCriteriaPage(BasePageTemplate):

    def render_form_and_formset_section(self, adapter):
        review = self.context["systematic_review"]
        section_id = f"{adapter.__name__}-section"
        child_records = adapter.model.objects.filter(review=review)

        if child_records:
            child_forms = h.fragment[
                (
                    ChildEditor(
                        adapter=adapter,
                        child=question,
                        prefix=f"screening-question-{question.pk}",
                    ).render()
                    for question in child_records
                )
            ]
        else:
            blank_editor = ChildEditor(
                adapter=adapter,
                child=adapter.model(review=review),
                prefix=f"screening-question-new-{uuid.uuid4().hex}",
            )
            child_forms = h.fragment[blank_editor.render()]

        return h.fragment[
            h.div(id=section_id)[h.div[child_forms],],
            h.div(".text-center")[
                h.button(
                    hx_get=adapter.get_new_url(review),
                    hx_target=f"#{section_id}",
                    hx_swap="beforeend",
                    type="button",
                    class_="btn btn-primary",
                )[adapter.add_button_text]
            ],
        ]

    def content(self):
        review = self.context["systematic_review"]

        return [
            bc.BreadcrumbTrailForSystematicReview(review)[
                bc.BreadcrumbItem(label=tdt("Screening criteria"))
            ],
            h.h1[tdt("Screening criteria")],
            h.h2[tdt("L1 screening questions")],
            self.render_form_and_formset_section(L1FormsetAdapter),
            h.h2[tdt("L2 screening questions")],
            # self.render_form_and_formset_section(L2FormsetAdapter),
            h.h2[tdt("Parameters")],
            # self.render_form_and_formset_section(ParameterFormsetAdapter),
        ]


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

    A single Question(parameter) + its options are the unit of saving. They have a prefix that ties them together and ensure they are separable from other forms on the page/request

    This helper can be composed by the add vs. edit views, for both models

    """

    adapter: FormsetAdapter
    child: ChildType
    prefix: str
    data: QueryDict | None = None

    @property
    def post_url(self):
        if self.child.pk is None:
            url = self.adapter.get_new_url(self.child.review)
        else:
            url = self.adapter.get_edit_url(self.child)

        return url + "?" + urlencode({"prefix": self.prefix})

    @cached_property
    def child_form(self):
        return self.adapter.FormClass(
            self.data,
            instance=self.child,
            prefix=self.prefix,
        )

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
        return FormSetCls(
            self.data,
            instance=self.child,
            prefix=f"{self.prefix}-options",
        )

    def save(self):
        with transaction.atomic():
            child = self.child_form.save()

            formset = self.option_formset
            if not formset.is_valid():
                raise ValueError("Option formset is not valid")
            formset.save()

        return child

    def render(self):

        post_url = self.post_url

        return h.form(
            hx_post=post_url,
            hx_target="this",
            hx_swap="outerHTML",
            class_="mb-4 border p-3 rounded",
        )[
            self.adapter.form_renderer(self.child_form),
            InlineFormset(
                self.option_formset,
                add_button_text=tdt("Add option"),
                form_renderer=self.adapter.option_form_renderer,
                can_add=True,
                aria_list_label=tdt("options"),
            ),
            h.div(".text-end")[
                h.button(type="submit", class_="btn btn-primary")[tdt("Save")],
            ],
        ]


class ChildEditorCreateView(MustAccessSystematicReviewMixin):
    adapter: FormsetAdapter

    @cached_property
    def editor(self):
        prefix = (
            self.request.GET.get("prefix") or f"child-new-{uuid.uuid4().hex}"
        )
        child = self.adapter.model(review=self.systematic_review)
        editor = ChildEditor(
            child=child,
            prefix=prefix,
            data=self.request.POST or None,
            adapter=self.adapter,
        )
        return editor

    def get(self, *args, **kwargs):
        return HttpResponse(self.editor.render())

    def post(self, *args, **kwargs):
        self.editor.save()
        content = self.editor.render()

        return HttpResponse(content)


class ChildEditorEditView(MustAccessSystematicReviewMixin):
    # type of formsetadapter
    adapter: type[FormsetAdapter]

    @cached_property
    def editor(self):
        prefix = self.request.GET["prefix"]
        question_id = self.kwargs["pk"]

        try:
            question = self.model.objects.get(pk=question_id)
        except self.model.DoesNotExist:
            raise ValueError("Invalid question ID")

        editor = ChildEditor(
            child=question,
            prefix=prefix,
            data=self.request.POST or None,
        )
        return editor

    def get(self, *args, **kwargs):
        return HttpResponse(self.editor.render())

    def post(self, *args, **kwargs):
        self.editor.save()
        content = self.editor.render()

        return HttpResponse(content)


@route(
    "systematic_reviews/<int:pk>/add_parameter_question",
    name="add_parameter_question",
)
class AddParameterQuestionView(ChildEditorCreateView):
    adapter = ParameterFormsetAdapter


@route(
    "parameter_questions/<int:pk>/edit",
    name="edit_parameter_question",
)
class EditParameterQuestionView(ChildEditorEditView):
    adapter = ParameterFormsetAdapter


@route(
    "systematic_reviews/<int:pk>/add_l1_screening_question",
    name="add_l1_question",
)
class AddL1ScreeningQuestionView(ChildEditorCreateView):
    adapter = L1FormsetAdapter


@route(
    "l1_screening_questions/<int:pk>/edit",
    name="edit_l1_question",
)
class EditL1ScreeningQuestionView(ChildEditorEditView):
    adapter = L1FormsetAdapter
