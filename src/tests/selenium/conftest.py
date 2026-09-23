from pathlib import Path

from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
)
from django.contrib.sessions.backends.db import SessionStore

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    selenium_dir = Path(__file__).parent
    for item in items:
        if item.path.is_relative_to(selenium_dir):
            item.add_marker(pytest.mark.selenium)
            item.add_marker(pytest.mark.django_db(transaction=True))


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(transactional_db):
    """The live server needs to see database changes made by each test."""


@pytest.fixture(scope="session")
def driver():
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    browser = webdriver.Chrome(options=options)
    yield browser
    browser.quit()


@pytest.fixture
def force_login(driver, live_server):
    def login(user):
        session = SessionStore()
        session[SESSION_KEY] = str(user.pk)
        session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
        session[HASH_SESSION_KEY] = user.get_session_auth_hash()
        session.save()

        driver.get(live_server.url + "/health/live")
        driver.add_cookie(
            {
                "name": settings.SESSION_COOKIE_NAME,
                "value": session.session_key,
                "path": "/",
            }
        )

    return login
