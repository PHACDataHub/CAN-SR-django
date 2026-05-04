from django.core.exceptions import PermissionDenied
from django.views import View

from phac_aspc.rules import test_rule


class MustPassRuleMixin(View):
    rule_name = None

    def check_rule(self, user):
        if self.rule_name is None:
            raise NotImplementedError(
                "Must set rule_name or override check_rule method"
            )

        return test_rule(self.rule_name, user)

    def dispatch(self, request, *args, **kwargs):
        if not self.check_rule(request.user):
            return self.handle_no_permission()

        return super().dispatch(request, *args, **kwargs)

    def handle_no_permission(self):

        raise PermissionDenied(
            "Permission denied: user does not pass required rule"
        )
