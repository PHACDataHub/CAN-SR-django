# pylint: disable=unused-import
# flake8: noqa

# This should only import from utility modules
# This should only be imported from domain modules
#   such as views, forms, queries, templates, services


from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import htpy
from data_fetcher import cache_within_request
from django.contrib import messages
from django.db import transaction
from django.db.models import QuerySet
from django.forms.models import ModelForm
from django.http import HttpResponse, HttpResponseRedirect, QueryDict
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    UpdateView,
    View,
)
from phac_aspc.rules import test_rule

from proj.form_util import StandardFormMixin
from proj.htpy import breadcrumbs
from proj.htpy.base_page import BasePageTemplate
from proj.htpy.generic_form import GenericForm, GenericFormWithContainer
from proj.htpy.util import (
    HtpyComponent,
    HtpyTemplatelessMixin,
    HtpyTemplateMixin,
    Markup,
    as_safe_renderable,
)
from proj.text import tdt, tm
from proj.view_util import MustPassRuleMixin
