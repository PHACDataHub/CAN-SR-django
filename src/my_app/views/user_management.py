from django import forms
from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.utils.timezone import localtime

import htpy as h

from proj.models import User

from my_app.constants import ADMIN_USER_GROUP
from my_app.router import route
from shortcuts import (
    BasePageTemplate,
    FormView,
    GenericForm,
    HtpyTemplateMixin,
    ListView,
    MustPassRuleMixin,
    StandardFormMixin,
    reverse,
    tdt,
)

ROLE_CHOICES = [
    ("nil", tdt("No role")),
    (ADMIN_USER_GROUP, tdt("Admin")),
]


class UserRoleForm(StandardFormMixin):
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        required=True,
        label=tdt("Role"),
    )


class CreateUserForm(UserRoleForm):
    email = forms.EmailField(
        required=True,
        label=tdt("Email"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["email", "role"])
        validation_message = tdt(
            "Enter a Government of Canada email ending in .gc.ca or @canada.ca."
        )
        self.fields["email"].widget.attrs.update(
            {
                "pattern": r"^[a-zA-Z0-9_.+\-]+@([a-zA-Z0-9\-]+\.gc\.ca|canada\.ca)$",
                "oninvalid": f"setCustomValidity('{validation_message}')",
                "oninput": "setCustomValidity('')",
            }
        )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if not (email.endswith("@canada.ca") or email.endswith(".gc.ca")):
            raise ValidationError(
                tdt(
                    "Enter a Government of Canada email ending in .gc.ca or @canada.ca."
                )
            )

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                tdt("An account for this email already exists.")
            )

        return email


class ManageUsersMixin(MustPassRuleMixin):
    rule_name = "is_admin"


class UserListPage(BasePageTemplate):
    def content(self):
        users = self.context["object_list"]

        return [
            h.div(".row.align-items-center.mb-3")[
                h.div(".col")[h.h1(".mb-0")[tdt("Users")]],
                h.div(".col-auto")[
                    h.a(
                        ".btn.btn-primary",
                        href=reverse("create_user"),
                    )[tdt("Create user")]
                ],
            ],
            h.div(".table-responsive")[
                h.table(".table.table-striped.align-middle")[
                    h.thead[
                        h.tr[
                            h.th(scope="col")[tdt("Name")],
                            h.th(scope="col")[tdt("Email")],
                            h.th(scope="col")[tdt("Role")],
                            h.th(scope="col")[tdt("Last login")],
                            h.th(scope="col")[tdt("Action")],
                        ]
                    ],
                    h.tbody[
                        [
                            h.tr[
                                h.th(scope="row")[
                                    user.get_full_name() or user.username
                                ],
                                h.td[user.email],
                                h.td[
                                    (
                                        tdt("Admin")
                                        if ADMIN_USER_GROUP in user.group_names
                                        else tdt("No role")
                                    )
                                ],
                                h.td[
                                    (
                                        localtime(user.last_login).strftime(
                                            "%Y-%m-%d %I:%M %p"
                                        )
                                        if user.last_login
                                        else ""
                                    )
                                ],
                                h.td[
                                    h.a(
                                        href=reverse(
                                            "edit_user", args=[user.pk]
                                        )
                                    )[tdt("Edit user")]
                                ],
                            ]
                            for user in users
                        ]
                    ],
                ]
            ],
        ]


class UserFormPage(BasePageTemplate):
    heading = None

    def content(self):
        return [
            h.h1[self.heading],
            h.form(method="post")[
                GenericForm(self.context["form"]),
                h.div(".d-flex.gap-2.justify-content-end")[
                    h.a(
                        ".btn.btn-secondary",
                        href=reverse("list_users"),
                    )[tdt("Cancel")],
                    h.button(".btn.btn-primary", type="submit")[tdt("Save")],
                ],
            ],
        ]


class CreateUserPage(UserFormPage):
    heading = tdt("Create user")


class EditUserPage(UserFormPage):
    heading = tdt("Edit user")


@route("users/", name="list_users")
class ListUsersView(ManageUsersMixin, ListView, HtpyTemplateMixin):
    template_component = UserListPage

    def get_queryset(self):
        return User.objects.all().order_by("username")


@route("users/create/", name="create_user")
class CreateUserView(ManageUsersMixin, FormView, HtpyTemplateMixin):
    form_class = CreateUserForm
    template_component = CreateUserPage

    def get_success_url(self):
        return reverse("list_users")

    def form_valid(self, form):
        email = form.cleaned_data["email"]
        user = User.objects.create_user(username=email, email=email)
        self.update_role(user, form.cleaned_data["role"])
        messages.success(self.request, tdt("User created"))
        return super().form_valid(form)

    @staticmethod
    def update_role(user, role):
        if role == ADMIN_USER_GROUP:
            group, _created = Group.objects.get_or_create(
                name=ADMIN_USER_GROUP
            )
            user.groups.add(group)


@route("users/<int:pk>/edit/", name="edit_user")
class EditUserView(ManageUsersMixin, FormView, HtpyTemplateMixin):
    form_class = UserRoleForm
    template_component = EditUserPage

    def get_user(self):
        return User.objects.get(pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        user = self.get_user()
        role = (
            ADMIN_USER_GROUP if ADMIN_USER_GROUP in user.group_names else "nil"
        )
        kwargs["initial"] = {"role": role}
        return kwargs

    def get_success_url(self):
        return reverse("list_users")

    def form_valid(self, form):
        user = self.get_user()
        user.groups.remove(*user.groups.filter(name=ADMIN_USER_GROUP))

        if form.cleaned_data["role"] == ADMIN_USER_GROUP:
            group, _created = Group.objects.get_or_create(
                name=ADMIN_USER_GROUP
            )
            user.groups.add(group)

        messages.success(self.request, tdt("User updated"))
        return super().form_valid(form)
