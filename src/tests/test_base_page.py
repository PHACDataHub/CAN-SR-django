from django.urls import reverse

from bs4 import BeautifulSoup


def test_base_page_footer(client, settings, tmp_path):
    settings.BASE_DIR = tmp_path / "src"
    (tmp_path / "version.txt").write_text("1.17.25\n", encoding="utf-8")

    response = client.get(reverse("login"))

    assert response.status_code == 200
    footer = BeautifulSoup(response.content, "html.parser").find("footer")
    assert "d-print-none" in footer["class"]
    assert "Version 1.17.25" in footer.get_text()
    assert [(link.text, link["href"]) for link in footer.select("a")] == [
        ("User agreement (todo)", "#"),
        ("Accessibility statement (todo)", "#"),
    ]
