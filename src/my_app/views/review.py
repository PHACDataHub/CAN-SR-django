from django import forms

from autocomplete import AutocompleteWidget

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
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    CreateView,
    DetailView,
    HtpyTemplateMixin,
    ListView,
    ModelForm,
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
        fields = ["title", "description", "language_model", "users"]

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop("request_user", None)
        super().__init__(*args, **kwargs)
        supported_models = LanguageModel.get_supported_models()
        default_model = supported_models.filter(is_default=True).first()
        self.fields["language_model"].queryset = supported_models
        self.fields["language_model"].empty_label = tdt(
            f"Default (currently {default_model})"
        )

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


@route("reviews/", name="review_list")
class ReviewListView(ListView, HtpyTemplateMixin):
    template_component = ReviewListPage

    def get_queryset(self):
        if test_rule("is_admin", self.request.user):
            return Review.objects.all().order_by("-created_at", "-id")

        return get_accessible_reviews(self.request.user.id)


@route("reviews/create/", name="create_review")
class CreateReviewView(CreateView, HtpyTemplateMixin):
    form_class = ReviewForm
    model = Review
    template_component = ReviewCreatePage

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
