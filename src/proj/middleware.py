import urllib
from uuid import uuid4

from django.conf import settings
from django.http.response import HttpResponseRedirect
from django.views import View

from data_fetcher.middleware import GlobalRequestMiddleware

from proj.logging import generate_context_id


class MustBeLoggedInMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if getattr(view_func, "allow_unauthenticated", False):
            return None

        if request.user.is_authenticated:
            return None

        elif "/login" not in request.path.lower():
            qs_params = dict(next=request.build_absolute_uri())
            querystring = urllib.parse.urlencode(qs_params)
            return HttpResponseRedirect(f"{settings.LOGIN_URL}?{querystring}")


class AllowUnauthenticatedMixin(View):
    """
    To be used with MustBeLoggedInMiddleware to opt-out of login_required
    """

    @classmethod
    def as_view(cls, *args, **kwargs):
        view = super().as_view(*args, **kwargs)
        view.allow_unauthenticated = True
        return view


class CustomGlobalRequestMiddleware(GlobalRequestMiddleware):
    def __call__(self, request):
        request.context_id = generate_context_id()
        return super().__call__(request)
