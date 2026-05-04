from my_app.htpy.systematic_review import (
    SystematicReviewCreatePage,
    SystematicReviewDetailPage,
    SystematicReviewEditPage,
    SystematicReviewListPage,
)
from my_app.models import SystematicReview, SystematicReviewUserLink
from my_app.queries import get_accessible_systematic_reviews
from my_app.router import route
from shortcuts import (
    CreateView,
    DetailView,
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
    transaction,
)


class MustAccessSystematicReviewMixin(MustPassRuleMixin):
    def check_rule(self, user):
        return test_rule(
            "can_access_systematic_review",
            user,
            self.kwargs.get("pk"),
        )


class SystematicReviewForm(ModelForm, StandardFormMixin):
    class Meta:
        model = SystematicReview
        fields = ["title", "description"]


@route("systematic-reviews/", name="systematic_review_list")
class SystematicReviewListView(ListView, HtpyTemplateMixin):
    template_component = SystematicReviewListPage

    def get_queryset(self):
        if test_rule("is_admin", self.request.user):
            return SystematicReview.objects.all().order_by(
                "-created_at", "-id"
            )

        return get_accessible_systematic_reviews(self.request.user.id)


@route("systematic-reviews/create/", name="create_systematic_review")
class CreateSystematicReviewView(CreateView, HtpyTemplateMixin):
    form_class = SystematicReviewForm
    model = SystematicReview
    template_component = SystematicReviewCreatePage

    def form_valid(self, form):
        with transaction.atomic():
            self.object = form.save()
            SystematicReviewUserLink.objects.create(
                user=self.request.user,
                systematic_review=self.object,
            )
            messages.success(self.request, tdt("Systematic review created"))
            return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("systematic_review_detail", args=[self.object.id])


@route("systematic-reviews/<int:pk>/edit/", name="edit_systematic_review")
class EditSystematicReviewView(
    UpdateView, MustAccessSystematicReviewMixin, HtpyTemplateMixin
):
    model = SystematicReview
    form_class = SystematicReviewForm
    template_component = SystematicReviewEditPage

    def form_valid(self, form):
        ret = super().form_valid(form)
        messages.success(self.request, tdt("Systematic review updated"))
        return ret

    def get_success_url(self):
        return reverse("systematic_review_detail", args=[self.object.id])


@route("systematic-reviews/<int:pk>/detail/", name="systematic_review_detail")
class SystematicReviewDetailView(
    MustAccessSystematicReviewMixin, DetailView, HtpyTemplateMixin
):
    model = SystematicReview
    template_component = SystematicReviewDetailPage
