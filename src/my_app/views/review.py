from django import forms
from django.http import HttpResponse

import htpy as h
from autocomplete import AutocompleteWidget

from proj.htpy.generic_form import GenericForm
from proj.htpy.modal_component import ModalComponent
from proj.models import User

from my_app.autocompletes import UserAutocomplete
from my_app.htpy.review import (
    ReviewCreatePage,
    ReviewDetailPage,
    ReviewEditPage,
    ReviewListPage,
)
from my_app.models import LanguageModel, Review, ReviewUserLink
from my_app.queries import get_accessible_reviews
from my_app.router import route
from my_app.views.view_utils import MustAccessReviewMixin, ReviewMixin
from shortcuts import (
    CreateView,
    DetailView,
    FormView,
    HtpyTemplateMixin,
    ListView,
    ModelForm,
    MustPassRuleMixin,
    StandardFormMixin,
    UpdateView,
    messages,
    redirect,
    reverse,
    tdt,
    test_rule,
    tm,
    transaction,
)


class ReviewForm(ModelForm, StandardFormMixin):
    is_deleted = forms.BooleanField(
        label=tdt("Is deleted"),
        help_text=tdt(
            "Also known as archive; this will remove links to this page."
        ),
        required=False,
    )
    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        label=tm("users"),
        widget=AutocompleteWidget(
            ac_class=UserAutocomplete,
            options={
                "multiselect": True,
                "placeholder": tdt("search for users"),
            },
        ),
        required=False,
    )

    class Meta:
        model = Review
        fields = [
            "title",
            "description",
            "language_model",
            "users",
            "is_deleted",
        ]

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop("request_user", None)
        super().__init__(*args, **kwargs)
        self.configure_initial_users()
        self.configure_language_model()
        self.configure_is_deleted()

    def configure_initial_users(self):
        if (
            not self.instance.pk
            and self.request_user
            and not test_rule("is_admin", self.request_user)
        ):
            self.initial.setdefault("users", [self.request_user])

    def configure_language_model(self):
        supported_models = LanguageModel.get_supported_models()
        default_model = supported_models.filter(is_default=True).first()
        self.fields["language_model"].queryset = supported_models
        self.fields["language_model"].empty_label = tdt(
            f"Default (currently {default_model})"
        )

    def configure_is_deleted(self):
        if not self.instance.pk:
            self.fields.pop("is_deleted")

    def clean_users(self):
        users = self.cleaned_data["users"]
        is_edit = bool(self.instance.pk)
        if (
            is_edit
            and self.request_user
            and not test_rule("is_admin", self.request_user)
            and self.request_user not in users
        ):
            raise forms.ValidationError(
                tdt("You must include yourself as an author.")
            )
        return users


class HardDeleteReviewForm(forms.Form):
    confirm = forms.BooleanField(
        label=tdt(
            "I confirm that I want to permanently hard-delete this review and all of its related data."
        ),
        required=True,
    )


@route("reviews/", name="review_list")
class ReviewListView(ListView, HtpyTemplateMixin):
    template_component = ReviewListPage

    def get_queryset(self):
        if test_rule("is_admin", self.request.user):
            return Review.objects.filter(is_deleted=False).order_by(
                "-created_at", "-id"
            )

        return [
            review
            for review in get_accessible_reviews(self.request.user.id)
            if not review.is_deleted
        ]


@route("reviews/create/", name="create_review")
class CreateReviewView(CreateView, HtpyTemplateMixin):
    form_class = ReviewForm
    model = Review
    template_component = ReviewCreatePage

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            self.object = form.save()
            ReviewUserLink.objects.get_or_create(
                user=self.request.user,
                review=self.object,
            )
            messages.success(self.request, tdt("Review created"))
            return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("review_detail", args=[self.object.id])


@route("reviews/<int:review_id>/edit/", name="edit_review")
class EditReviewView(UpdateView, MustAccessReviewMixin, HtpyTemplateMixin):
    model = Review
    pk_url_kwarg = "review_id"
    form_class = ReviewForm
    template_component = ReviewEditPage

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        ret = super().form_valid(form)
        messages.success(self.request, tdt("Review updated"))
        return ret

    def get_success_url(self):
        return reverse("edit_review", args=[self.object.id])


@route("reviews/<int:review_id>/detail/", name="review_detail")
class ReviewDetailView(MustAccessReviewMixin, DetailView, HtpyTemplateMixin):
    model = Review
    pk_url_kwarg = "review_id"
    template_component = ReviewDetailPage


@route("reviews/<int:review_id>/hard-delete/", name="hard_delete_review")
class HardDeleteReviewView(MustPassRuleMixin, ReviewMixin, FormView):
    form_class = HardDeleteReviewForm
    form_id = "hard-delete-review-form"

    def check_rule(self, user):
        return test_rule("can_hard_delete_review", user, self.review)

    def get(self, request, *args, **kwargs):
        return HttpResponse(self.render_modal(self.get_form()))

    def form_valid(self, form):
        self.review.delete()
        messages.success(self.request, tdt("Review hard-deleted."))
        success_url = reverse("review_list")

        if self.request.headers.get("HX-Request") == "true":
            return HttpResponse(headers={"HX-Redirect": success_url})

        return redirect(success_url)

    def form_invalid(self, form):
        return HttpResponse(self.render_modal(form))

    def render_modal(self, form):
        hard_delete_url = reverse("hard_delete_review", args=[self.review.id])
        footer = h.fragment[
            h.button(
                type="button",
                class_="btn btn-secondary",
                data_modal_close=True,
            )[tdt("Cancel")],
            h.button(
                ".btn.btn-danger",
                type="submit",
                form=self.form_id,
            )[tdt("Hard-delete review")],
        ]
        body = h.form(
            id=self.form_id,
            method="post",
            action=hard_delete_url,
            hx_post=hard_delete_url,
            hx_target="#modal-slot",
            hx_swap="innerHTML",
        )[GenericForm(form)]

        return ModalComponent(
            title=tdt("Hard-delete review"),
            footer=footer,
            modal_id="hard-delete-review-modal",
        )[body]
