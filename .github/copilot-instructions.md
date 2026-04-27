# What's in this repo

It's a template django project, most often forked for internal government applications for the public health agency of Canada.

there are two main packages:

- proj: configuration and things that could be re-used in other projects (e.g. settings, router, translations, custom fields). Much boilerplate
- my_app: example app, a project-management app showcasing various features

# App development notes

code style

- classes
  - django.utils.functional.cached_property decorator encouraged, especially for form/formset/model instantiation
  - Split complex methods using the single-resp principle
- prefer conditional blocks to ternary expr
- prefer comprehensions to loops
- Dont over-comment obvious code

Commands: Always run `python src/manage.py {command}` to avoid path errors. Run `makemigrations` as needed when touching models

Localization

- All user-facing text should be externalized and rendered via tm(). In jinja, tm is a global, in python, it's `proj.text.tm`
- Every (unique) tm() key should have an entry in the `src/proj/translations.py` dict. If adding new text, add translations at bottom of dict
- if the task is prototype-ish in nature, don't worry about translations, but use `tdt` to mark strings, this way we don't risk forgetting translating literals later on. `tdt` is a no-op that just returns the string, but serves as a reminder to add the key to translations.py later

Rendering

- use htpy to render markup, not plain strings
- jinja2 is being phased out in favor of htpy

CSS

- CSS overrides in src/static/site.css
- Use bootstrap 5 classes, prefer `.{row}{col}` to .d-flex when equally valid

Models

- Follow patterns in existing models, e.g. versioning decorator, custom fields, verbose_name
- Avoid N+1 queries with select_related and prefetch_related as needed

Views:

- use class-based views, django generic views encouraged
- all views registered in urls.py
- Use HtpyTemplateMixin when building views that need a traditional template_name, e.g. to interop with generic views
- For smaller views with small responses, e.g. htmx endpoints, can return htpy nodes directly from the view

Forms

- ModelForm and proj.form_util.StandardFormMixin encouraged
- Prefer rendering forms using macros and the generic_form jinja partial
- Manual rendering of fields discouraged unless prompted

Authorization

- Use django-rules (rules.py), with test_rule checks in views.py as needed
- Always import `phac_aspc.rules.test_rule`, dont import from local rules
- Views with perm-logic should use a mixin, usually override dispatch()
- in jinja use global `respects_rule()`

UI/UX

- Prioritize WCAG, unprompted icons discouraged
- Plain HTML/CSS > HTMX > Vanilla JS, NO jquery
- Modals discouraged, follow existing pattern strictly

# Testing

Write pytests in the src/tests/, focus on integration tests of views, unit tests for helpers

- No need for @mark.django_db, tests already have db access and run in transactions
- Use factory-boy factories (in model_factories modules) and freezegun when applicable
- use `with patch_rules(...)` to test perms

Most tests look something like this:

```
def test_something(vanilla_user_client):
    some_record = Foo.objects.create(...)
    url = reverse("foo", args=[some_record.id])
    with patch_rules(can_access_foo=False):
        resp = vanilla_user_client.get(url)
        assert resp.status_code == 403
    with patch_rules(can_access_foo=True):
        resp = vanilla_user_client.get(url)
        assert resp.status_code == 200
```

See existing tests for examples before writing new ones

Tests can be run

- global `python src/manage.py test src/`
- specific files `python src/manage.py test src/tests/test_foo.py`
- single funcs `python src/manage.py test src/tests/test_foo.py::test_bar`

# Formatting

We use black/isort/djlint to format .py/.jinja2. It can be run globally, but preferably with relevant file arguments:

1. `isort src/`
2. `black src/`
3. `djlint --reformat src/` (rarely needed, only for jinja2)

# Behavior instructions

- Prefer working minimal solutions
- Dont go beyond what was requested
- When in doubt look for similar examples in the repo
- Follow existing patterns
