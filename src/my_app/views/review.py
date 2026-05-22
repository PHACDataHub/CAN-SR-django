from my_app.htpy.review import (
    ReviewCreatePage,
    ReviewDetailPage,
    ReviewEditPage,
    ReviewListPage,
)
from my_app.models import Review, ReviewUserLink
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
    transaction,
)


class ReviewForm(ModelForm, StandardFormMixin):
    class Meta:
        model = Review
        fields = ["title", "description"]


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
            ReviewUserLink.objects.create(
                user=self.request.user,
                review=self.object,
            )
            messages.success(self.request, tdt("Review created"))
            return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("review_detail", args=[self.object.id])


@route("reviews/<int:pk>/edit/", name="edit_review")
class EditReviewView(UpdateView, MustAccessReviewMixin, HtpyTemplateMixin):
    model = Review
    form_class = ReviewForm
    template_component = ReviewEditPage

    def form_valid(self, form):
        ret = super().form_valid(form)
        messages.success(self.request, tdt("Review updated"))
        return ret

    def get_success_url(self):
        return reverse("review_detail", args=[self.object.id])


@route("reviews/<int:pk>/detail/", name="review_detail")
class ReviewDetailView(MustAccessReviewMixin, DetailView, HtpyTemplateMixin):
    model = Review
    template_component = ReviewDetailPage
