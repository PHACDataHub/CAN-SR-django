When running scripts or tests, always use ./venv/bin/python or specify the full path to your virtual environment interpreter

# What's in this repo

This is evidence-synthesis / systematic-review workflow software for the public health agency of Canada.

there are two main packages:

- proj: configuration and things that could be re-used in other projects (e.g. settings, router, custom fields). Much boilerplate.
  - also includes all translations
- my_app: the 'domain specific' application with all the models, views, etc.

# App development notes

code style

- classes
  - django.utils.functional.cached_property decorator encouraged, especially for form/formset/model instantiation
  - Split complex methods using the single-resp principle
- prefer conditional blocks and extra variables to ternary expr
  - especially if ternaries are nested or when both branches are non-null
- prefer comprehensions to loops
- Dont over-comment obvious code

Commands: Always run `python src/manage.py {command}` to avoid path errors. Run `makemigrations` as needed when touching models

Localization

- Most of the time, we want prototypes generated, and want all new user-facing text to be wrapped in `tdt()`, this marks strings as "todo" for translation later.
- If explicitly told we want translations, properly externalize strings as follows:
  - text should be externalized and rendered via tm() (`proj.text.tm`)
  - Every (unique) tm() key should have an entry in the `src/proj/translations.py` dict. If adding new text, add translations at bottom of dict

Rendering or "templates"

- we use htpy to render, rather plain strings or string-based templates
- this is react-like, but server-side
- sometimes these are formal "templates", that receive a request and context object (and plug into django's template API), other times it's a simple function return htpy nodes
- to DRY-out (dont repeat yourself) presentational code, prefer composition over inheritance
- generally, htpy components should be PascalCase, and not \_private
- For complex presentation components, you can use class-based HtpyComponents, this unlocks inheritance and single-responsibility methods
- Feel free to use data_fetcher's get_request() and derivative context-based approaches to get data into components, rather than passing everything through multiple layers of composition

CSS

- CSS overrides in src/static/site.css
- Use bootstrap 5 classes, prefer `.{row}{col}` to .d-flex when equally valid

Models

- Follow patterns in existing models, e.g. versioning decorator, custom fields, verbose_name
- Avoid N+1 queries with select_related and prefetch_related as needed

Views:

- default to sync views, only ever use async if asked explicitly
- use class-based views, django generic views encouraged
- all views registered in urls.py
- Use HtpyTemplateMixin when building views that need a traditional template_name, e.g. to interop with generic views
  - if a view has a template, that template should take care of all presentational concerns, including even querying additional data used by render logic
- For smaller views with small responses (e.g. htmx endpoints) return htpy nodes directly from the view

Forms

- ModelForm and proj.form_util.StandardFormMixin encouraged
- Prefer rendering forms using GenericForm component, manual rendering of individual fields is discouraged unless prompted

Authorization

- Use django-rules (rules.py), with test_rule checks in views.py as needed
- Always import `phac_aspc.rules.test_rule`, dont import from local rules
- Views with perm-logic should use a mixin, usually override dispatch()

UI/UX

- Prioritize WCAG, unprompted icons discouraged
- Plain HTML/CSS > HTMX > Vanilla JS, NO jquery
- Modals discouraged, follow existing pattern strictly

Javascript

- avoid writing custom JS when possible, prefer HTMX
- inline JS in htpy script tags is ugly, if more than 3 lines, put it in a separate file in src/static, link with src=static_no_cache attr
- small bits of data, like ids, flags or labels, can be passed via `data-*` attributes and accessed via a small helper function
  - this includes translations, although the tdt() function is also available in JS files for demo-text

# Testing

Write pytests in the src/tests/, focus on integration tests of views, unit tests for helpers

- No need for @mark.django_db, tests already have db access and run in transactions
- Use factory-boy factories (in model_factories modules) and freezegun when applicable
- use `with patch_rules(...)` to test perms

Most tests look something like this:

```
def test_something(vanilla_client):
    some_record = Foo.objects.create(...)
    url = reverse("foo", args=[some_record.id])
    with patch_rules(can_access_foo=False):
        resp = vanilla_client.get(url)
        assert resp.status_code == 403
    with patch_rules(can_access_foo=True):
        resp = vanilla_client.get(url)
        assert resp.status_code == 200
```

See existing tests for examples before writing new ones

You may need to run pytests from the src/ dir. Example commands:

- run all tests `pytest`
- specific files `pytest src/tests/test_foo.py`
- single funcs `pytest src/tests/test_foo.py::test_bar`

# Formatting

We use black/isort to format .py files. It can be run globally, but preferably with relevant file arguments:

1. `isort src/`
2. `black src/`

# Behavior instructions

- Prefer working minimal solutions
- Dont go beyond what was requested
- When in doubt look for similar examples in the repo
- Follow existing patterns
