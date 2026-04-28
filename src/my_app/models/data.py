from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin, track_versions
from proj.models import User
from proj.text import tdt

from .model_util import BilingualDescriptionMixin, BilingualNameMixin


@track_versions
@add_to_admin
class Project(BilingualDescriptionMixin, BilingualNameMixin):
    ACTIVE_STATUS = "active"
    ONHOLD_STATUS = "onhold"
    CANCELLED_STATUS = "cancelled"
    COMPLETED_STATUS = "completed"
    STATUS_CHOICES = (
        (ACTIVE_STATUS, tdt("Active")),
        (ONHOLD_STATUS, tdt("On Hold")),
        (CANCELLED_STATUS, tdt("Cancelled")),
        (COMPLETED_STATUS, tdt("Completed")),
    )

    status = fields.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        null=False,
        default=ACTIVE_STATUS,
    )
    project_type = fields.ForeignKey(
        "my_app.ProjectType",
        related_name="projects",
        on_delete=models.CASCADE,
        null=True,
        verbose_name=tdt("Project Type"),
    )
    tags = fields.ManyToManyField(
        "my_app.ProjectTag", related_name="projects", blank=True
    )

    def get_user_role(self, user):
        return self.roles.filter(user=user).first()


@track_versions
@add_to_admin
class ProjectTask(BilingualDescriptionMixin, BilingualNameMixin):
    project = fields.ForeignKey(
        Project, related_name="tasks", on_delete=models.CASCADE
    )


@add_to_admin
class Document(models.Model):
    class Meta:
        ordering = ["-uploaded_at", "-id"]

    document_type = fields.CharField(
        max_length=100, verbose_name=tdt("Document type")
    )
    file = fields.FileField(
        upload_to="documents/", verbose_name=tdt("Document file")
    )
    source_url = fields.URLField(
        blank=True, null=True, verbose_name=tdt("Source URL")
    )
    uploaded_by = fields.ForeignKey(
        User,
        related_name="documents",
        on_delete=models.CASCADE,
        verbose_name=tdt("Associated user"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True, verbose_name=tdt("Upload date")
    )

    def __str__(self):
        return f"{self.document_type}: {self.file.name}"
