from my_app.models import SystematicReview
from shortcuts import MustPassRuleMixin, cached_property, test_rule


class MustAccessSystematicReviewMixin(MustPassRuleMixin):
    def check_rule(self, user):
        return test_rule(
            "can_access_systematic_review",
            user,
            self.kwargs.get("pk"),
        )

    @cached_property
    def systematic_review(self):
        return SystematicReview.objects.get(pk=self.kwargs["pk"])

    @property
    def review(self):
        return self.systematic_review

    def get_context_data(self, *args, **kwargs):
        return {
            **super().get_context_data(*args, **kwargs),
            "review": self.systematic_review,
            "systematic_review": self.systematic_review,
        }
