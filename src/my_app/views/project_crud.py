from typing import Any

from django import http
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.query import QuerySet
from django.forms.models import BaseModelForm, ModelForm
from django.http import HttpResponse
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

import htpy
from phac_aspc.rules import test_rule

from proj.form_util import StandardFormMixin
from proj.htpy.util import HtpyTemplatelessMixin, HtpyTemplateMixin
from proj.text import tdt

from my_app.htpy.project_crud import (
    CreateProjectPage,
    EditProjectPage,
    ListProjectsPage,
)
from my_app.htpy.project_crud import (
    ProjectPreviewModal as ProjectPreviewModalComponent,
)
from my_app.models import Project, ProjectUserRole
from my_app.queries import get_project_qs_for_user
from my_app.router import route


class ProjectForm(ModelForm, StandardFormMixin):
    class Meta:
        model = Project
        fields = [
            "name_en",
            "name_fr",
            "description_en",
            "description_fr",
            "project_type",
            "tags",
        ]


@route("projects/create/", name="create_project")
class CreateProject(CreateView, HtpyTemplateMixin):
    form_class = ProjectForm
    model = Project
    template_component = CreateProjectPage

    def form_valid(self, form):
        with transaction.atomic():
            self.object = form.save()
            ProjectUserRole.objects.create(
                project=self.object,
                user=self.request.user,
                role=ProjectUserRole.LEADER_ROLE,
            )
            messages.add_message(
                self.request, messages.SUCCESS, tdt("Project created")
            )
            return super().form_valid(form)

    def get_success_url(self):
        return reverse("edit_project", args=[self.object.id])


@route("projects/<int:pk>/edit/", name="edit_project")
class EditProject(UpdateView, HtpyTemplateMixin):
    model = Project
    form_class = ProjectForm
    template_component = EditProjectPage

    def form_valid(self, form):
        ret = super().form_valid(form)
        messages.add_message(
            self.request, messages.SUCCESS, tdt("Project updated")
        )
        return ret

    def get_success_url(self):
        # redirect to self
        return self.request.build_absolute_uri()

    def dispatch(self, request, *args: Any, **kwargs) -> HttpResponse:
        if not test_rule(
            "can_modify_project", self.request.user, self.kwargs.get("pk")
        ):
            raise PermissionDenied(tdt("You can't view this project"))

        return super().dispatch(request, *args, **kwargs)


@route("projects/", name="list_projects")
class ListProjects(ListView, HtpyTemplateMixin):
    template_component = ListProjectsPage

    def get_queryset(self):
        return get_project_qs_for_user(self.request.user)


@route("projects/<int:pk>/preview_modal/", name="preview_project_modal")
class ProjectPreviewModal(DetailView, HtpyTemplateMixin):
    model = Project
    template_component = ProjectPreviewModalComponent

    def dispatch(self, request, *args, **kwargs):
        if not test_rule(
            "can_view_project", self.request.user, self.kwargs.get("pk")
        ):
            raise PermissionDenied(tdt("You can't view this project"))

        return super().dispatch(request, *args, **kwargs)


@route("projects/<int:pk>/detail/", name="project_detail")
class ProjectDetail(DetailView, HtpyTemplatelessMixin):
    """
    This view couples rendering and view logic more tightly,
    this can be useful for smaller views,
    or more generally, if managed carefully
    """

    model = Project

    def title(self):
        return self.object.name_en

    def content(self):
        return htpy.div[
            htpy.h1[self.object.name_en],
            htpy.a({"href": reverse("list_projects")})[tdt("Back to list")],
            htpy.a({"href": reverse("edit_project", args=[self.object.id])})[
                tdt("Edit project")
            ],
            htpy.p[self.object.description_en],
        ]
