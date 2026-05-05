from shortcuts import MustPassRuleMixin, test_rule


class MustAccessSystematicReviewMixin(MustPassRuleMixin):
    def check_rule(self, user):
        return test_rule(
            "can_access_systematic_review",
            user,
            self.kwargs.get("pk"),
        )
