from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path, re_path

from phac_aspc.django.helpers.urls import urlpatterns as phac_aspc_helper_urls

from my_app.urls import urlpatterns as my_app_urls

from .views import LoginView, LogoutView, RootView

dev_routes = []
if settings.DEBUG and settings.ENABLE_DEBUG_TOOLBAR:
    import debug_toolbar

    dev_routes += [re_path(r"^__debug__/", include(debug_toolbar.urls))]


urlpatterns = i18n_patterns(
    path("phac_admin/", admin.site.urls),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", include(my_app_urls)),
    prefix_default_language=False,
) + [
    re_path("^$", RootView.as_view(), name="root"),
    *phac_aspc_helper_urls,
    *dev_routes,
]
