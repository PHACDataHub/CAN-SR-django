from django.test.client import Client
from django.urls import reverse

from my_app.model_factories import ProjectFactory
from my_app.models import Project, ProjectTag, ProjectType, ProjectUserRole


def test_create_project(admin_client, admin_user):
    url = reverse("create_project")
    response = admin_client.get(url)
    assert response.status_code == 200

    bad_data = {
        "name": "Test Project",
    }
    response = admin_client.post(url, bad_data)
    assert response.status_code == 200
    assert not response.context["form"].is_valid()
    assert response.context["form"].errors["name_en"]

    good_data = {
        "name_en": "Test Project",
        "name_fr": "Le Test Project",
        "description_en": "This is a test project",
        "description_fr": "C'est un test project",
        "project_type": ProjectType.objects.get(code="construction").pk,
        "tags": [ProjectTag.objects.get(name_en="Expensive").pk],
    }

    response = admin_client.post(url, good_data)
    assert response.status_code == 302
    new_proj = Project.objects.first()
    assert new_proj.name_en == "Test Project"
    assert new_proj.name_fr == "Le Test Project"
    assert new_proj.description_en == "This is a test project"
    assert new_proj.description_fr == "C'est un test project"
    assert new_proj.project_type.code == "construction"
    assert new_proj.tags.first().name_en == "Expensive"
    assert (
        new_proj.get_user_role(admin_user).role == ProjectUserRole.LEADER_ROLE
    )


def test_edit_project(admin_client, admin_user):
    proj = ProjectFactory()
    url = reverse("edit_project", args=[proj.id])
    response = admin_client.get(url)
    assert response.status_code == 200

    bad_data = {
        "name": "Test Project",
    }
    response = admin_client.post(url, bad_data)
    assert response.status_code == 200
    assert not response.context["form"].is_valid()
    assert response.context["form"].errors["name_en"]

    good_data = {
        "name_en": "Test Project",
        "name_fr": "Le Test Project",
        "description_en": "This is a test project",
        "description_fr": "C'est un test project",
        "project_type": ProjectType.objects.get(code="construction").pk,
        "tags": [ProjectTag.objects.get(name_en="Expensive").pk],
    }

    response = admin_client.post(url, good_data)
    assert response.status_code == 302
    proj = Project.objects.first()
    assert proj.name_en == "Test Project"
    assert proj.name_fr == "Le Test Project"
    assert proj.description_en == "This is a test project"
    assert proj.description_fr == "C'est un test project"
    assert proj.project_type.code == "construction"
    assert proj.tags.first().name_en == "Expensive"


def test_project_detail(admin_client):
    proj = ProjectFactory()
    url = reverse("project_detail", args=[proj.id])
    response = admin_client.get(url)
    assert response.status_code == 200
