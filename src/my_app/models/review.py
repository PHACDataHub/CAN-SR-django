from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin, track_versions
from proj.models import User
from proj.text import tm


@track_versions
@add_to_admin
class Review(models.Model):
    class Meta:
        verbose_name = tm("systematic_review")
        verbose_name_plural = tm("systematic_reviews")
        ordering = ["-created_at", "-id"]

    title = fields.CharField(
        max_length=255, verbose_name=tm("systematic_review_title")
    )
    description = fields.TextField(
        verbose_name=tm("systematic_review_description")
    )
    created_at = fields.DateTimeField(
        auto_now_add=True, verbose_name=tm("systematic_review_created_at")
    )

    def __str__(self):
        return self.title


@add_to_admin
class ReviewUserLink(models.Model):

    user = fields.ForeignKey(
        User,
        related_name="review_links",
        on_delete=models.CASCADE,
    )
    review = fields.ForeignKey(
        Review,
        related_name="user_links",
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return f"{self.user_id} -> {self.review_id}"
