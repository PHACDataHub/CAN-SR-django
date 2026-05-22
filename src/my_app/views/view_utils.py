from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def url_with_same_params(request, path=None, **new_params):
    if path is None:
        path = request.path

    return _url_with_params(path, request.GET, **new_params)


def _url_with_params(path, current_params, **new_params):
    parsed_url = urlsplit(path)

    merged_params = list(parse_qsl(parsed_url.query, keep_blank_values=True))
    for key, values in current_params.lists():
        merged_params = [pair for pair in merged_params if pair[0] != key]
        merged_params.extend((key, value) for value in values)

    for key, value in new_params.items():
        merged_params = [pair for pair in merged_params if pair[0] != key]

        if value is None:
            continue

        if isinstance(value, (list, tuple)):
            merged_params.extend((key, str(item)) for item in value)
        else:
            merged_params.append((key, str(value)))

    return urlunsplit(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            urlencode(merged_params, doseq=True),
            parsed_url.fragment,
        )
    )
