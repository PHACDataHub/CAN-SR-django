from django.urls import path

from django_routify import include_router

from . import views
from .router import router

urlpatterns = [
    include_router(router),
]
