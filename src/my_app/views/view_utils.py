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
