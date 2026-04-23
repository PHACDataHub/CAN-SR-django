from django.urls import reverse


def test_modal_demo_page_renders_all_examples(admin_client):
    response = admin_client.get(reverse("modal_demo"))

    assert response.status_code == 200

    content = response.content.decode()

    assert "Modal demo" in content
    assert "Open static modal" in content
    assert 'id="static-modal"' in content
    assert 'id="nested-modal"' in content
    assert reverse("modal_demo_htmx") in content
    assert reverse("modal_demo_form") in content
    assert 'id="dropdown-demo-toggle"' in content


def test_modal_demo_htmx_view_returns_modal_fragment(admin_client):
    response = admin_client.get(reverse("modal_demo_htmx"))

    assert response.status_code == 200

    content = response.content.decode()

    assert "HTMX modal" in content
    assert 'id="htmx-modal"' in content
    assert "modal-lg" in content
    assert 'id="nested-from-htmx"' in content
    assert "<html" not in content


def test_modal_demo_form_view_get_renders_form_fragment(admin_client):
    url = reverse("modal_demo_form")

    response = admin_client.get(url)

    assert response.status_code == 200

    content = response.content.decode()

    assert "Form modal" in content
    assert f'hx-post="{url}"' in content
    assert 'name="name"' in content
    assert 'name="email"' in content
    assert "<html" not in content


def test_modal_demo_form_view_post_invalid_rerenders_form_errors(admin_client):
    response = admin_client.post(
        reverse("modal_demo_form"),
        {"name": "", "email": "not-an-email"},
    )

    assert response.status_code == 200

    content = response.content.decode()

    assert "<form" in content
    assert "This field is required." in content
    assert "Enter a valid email address." in content
    assert "HX-Trigger" not in response.headers
    assert "HX-Trigger-After-Settle" not in response.headers


def test_modal_demo_form_view_post_valid_returns_success_fragment(
    admin_client,
):
    response = admin_client.post(
        reverse("modal_demo_form"),
        {"name": "Jane Example", "email": "jane@example.com"},
    )

    assert response.status_code == 200
    assert response.headers["HX-Trigger-After-Settle"] == "modal-close"
    assert response.headers["HX-Reswap"] == "none"

    content = response.content.decode()

    assert 'id="message-bar"' in content
    assert "alert-success" in content
    assert "form submitted successfully" in content
