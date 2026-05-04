from data_fetcher.middleware import GlobalRequest

# creating a variable called test_rules triggers pytest to run it as a test! annoying!
from phac_aspc.rules import test_rule as my_test_rule

from proj.models import User

from my_app.model_factories import (
    ProjectFactory,
    SystematicReviewFactory,
    SystematicReviewUserLinkFactory,
)
from my_app.services import (
    set_project_contributor,
    set_project_leader,
    set_project_spectator,
)


def test_admin_has_all_access(admin_user):
    assert my_test_rule("is_admin", admin_user)

    p = ProjectFactory()
    assert my_test_rule("can_view_project", admin_user, p.id)
    assert my_test_rule("can_modify_project", admin_user, p.id)


def test_leader_role():
    leader = User.objects.create()
    proj = ProjectFactory()
    other_proj = ProjectFactory()
    set_project_leader(proj, leader)

    assert not my_test_rule("is_admin", leader)
    assert my_test_rule("is_project_leader", leader, proj.id)
    assert not my_test_rule("is_project_leader", leader, other_proj.id)
    assert my_test_rule("can_view_project", leader, proj.id)
    assert my_test_rule("can_modify_project", leader, proj.id)
    assert not my_test_rule("can_view_project", leader, other_proj.id)
    assert not my_test_rule("can_modify_project", leader, other_proj.id)


def test_contributor_role():
    u = User.objects.create()
    proj = ProjectFactory()
    other_proj = ProjectFactory()
    set_project_contributor(proj, u)

    assert not my_test_rule("is_admin", u)
    assert not my_test_rule("is_project_leader", u, proj.id)
    assert my_test_rule("is_project_contributor", u, proj.id)
    assert not my_test_rule("is_project_contributor", u, other_proj.id)
    assert my_test_rule("can_view_project", u, proj.id)
    assert my_test_rule("can_modify_project_tasks", u, proj.id)
    assert not my_test_rule("can_modify_project_tasks", u, other_proj.id)
    assert not my_test_rule("can_view_project", u, other_proj.id)


def test_spectator_role():
    u = User.objects.create()
    proj = ProjectFactory()
    other_proj = ProjectFactory()
    set_project_spectator(proj, u)

    assert not my_test_rule("is_admin", u)
    assert not my_test_rule("is_project_leader", u, proj.id)
    assert not my_test_rule("is_project_contributor", u, proj.id)
    assert my_test_rule("is_project_spectator", u, proj.id)
    assert not my_test_rule("is_project_spectator", u, other_proj.id)
    assert my_test_rule("can_view_project", u, proj.id)
    assert not my_test_rule("can_modify_project_tasks", u, proj.id)


def test_systematic_review_access_rule(admin_user):
    linked_user = User.objects.create(username="linked-user")
    other_user = User.objects.create(username="other-user")
    linked_review = SystematicReviewFactory()
    other_review = SystematicReviewFactory()
    SystematicReviewUserLinkFactory(
        user=linked_user, systematic_review=linked_review
    )

    with GlobalRequest():
        assert my_test_rule(
            "can_access_systematic_review", admin_user, linked_review.id
        )
        assert my_test_rule(
            "can_access_systematic_review", linked_user, linked_review.id
        )
        assert not my_test_rule(
            "can_access_systematic_review", linked_user, other_review.id
        )
        assert not my_test_rule(
            "can_access_systematic_review", other_user, linked_review.id
        )
