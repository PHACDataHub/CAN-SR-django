from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt


@add_to_admin
class DemoTaskRun(models.Model):
    class Meta:
        ordering = ["-completed_at", "-id"]

    task_result_id = fields.CharField(
        max_length=64, unique=True, verbose_name=tdt("Task result ID")
    )
    kind = fields.CharField(
        max_length=20, default="sync", verbose_name=tdt("Kind")
    )
    label = fields.CharField(max_length=200, verbose_name=tdt("Label"))
    record_count = models.PositiveIntegerField()
    attempt = models.PositiveIntegerField(default=1)
    completed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind}: {self.label} ({self.record_count})"
