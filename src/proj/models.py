import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils.functional import cached_property

from proj.model_util import add_to_admin
from proj.text import tdt


class GroupPrefetcherManager(UserManager):
    """
    groups are used for authorization and are accessed every request
    """

    use_for_related_fields = True

    def get_queryset(self):
        return (
            super(GroupPrefetcherManager, self)
            .get_queryset()
            .prefetch_related(models.Prefetch("groups", to_attr="group_list"))
        )


@add_to_admin
class User(AbstractUser):
    class Meta:
        base_manager_name = "objects"

    objects = GroupPrefetcherManager()

    @cached_property
    def _all_groups(self):
        return list(self.groups.all())

    @property
    def group_names(self):
        return [g.name for g in self._all_groups]


@add_to_admin
class TaskGroup(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", tdt("Waiting")
        SUCCESSFUL = "successful", tdt("Successful")
        FAILED = "failed", tdt("Failed")

    class CompletionPolicy(models.TextChoices):
        ALL_SUCCESS = "all_success", tdt("All tasks successful")
        ALL_SETTLED = "all_settled", tdt("All tasks settled")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.WAITING,
    )
    completion_policy = models.CharField(
        max_length=20,
        choices=CompletionPolicy.choices,
        default=CompletionPolicy.ALL_SUCCESS,
    )
    members = models.JSONField(default=dict)
    results = models.JSONField(default=dict)
    errors = models.JSONField(default=dict)
    callback_task_path = models.CharField(max_length=512, blank=True)
    callback_task_backend = models.CharField(max_length=255, blank=True)
    callback_kwargs = models.JSONField(default=dict)
    error_callback_task_path = models.CharField(max_length=512, blank=True)
    error_callback_task_backend = models.CharField(max_length=255, blank=True)
    error_callback_kwargs = models.JSONField(default=dict)
    callback_task_result_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_latest_with_key(self):
        if not self.key:
            return True

        latest_id = (
            TaskGroup.objects.filter(key=self.key)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
        return latest_id == self.id
