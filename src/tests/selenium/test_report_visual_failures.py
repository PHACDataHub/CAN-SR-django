from pathlib import Path

from tests.selenium import report_visual_failures as report


def _set_ci_environment(monkeypatch, attachment_token="bot-token"):
    values = {
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_RUN_ID": "1234",
        "GITHUB_TOKEN": "actions-token",
        "PR_NUMBER": "17",
        "VISUAL_ARTIFACT_URL": "https://github.com/example/repo/actions/runs/1234/artifacts/1",
        "VISUAL_REGRESSION_TOKEN": attachment_token,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _failures(tmp_path, count):
    failures = []
    for index in range(count):
        directory = tmp_path / f"screen-{index:02d}"
        directory.mkdir()
        (directory / "diff.png").write_bytes(b"png")
        failures.append(directory)
    return failures


def test_updates_existing_visual_comment_with_at_most_five_diffs(
    monkeypatch, tmp_path
):
    _set_ci_environment(monkeypatch)
    failures = _failures(tmp_path, 6)
    monkeypatch.setattr(report, "failed_screenshots", lambda: failures)
    monkeypatch.setattr(
        report,
        "comments",
        lambda *args: [
            {
                "id": 42,
                "body": report.MARKER,
                "user": {"login": "visual-bot"},
            }
        ],
    )
    monkeypatch.setattr(
        report,
        "gh",
        lambda token, *args: (
            '{"login": "visual-bot"}'
            if args == ("api", "user")
            else "--attach"
        ),
    )
    calls = []
    monkeypatch.setattr(
        report,
        "write_comment",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        report, "remove_duplicate_comments", lambda *args: None
    )

    report.main()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs["edit_last"] is True
    assert len(args[4]) == 5
    assert "6 screenshots failed" in args[3]
    assert args[3].count("![Visual diff") == 5


def test_more_than_eight_failures_updates_summary_without_attachments(
    monkeypatch, tmp_path
):
    _set_ci_environment(monkeypatch)
    failures = _failures(tmp_path, 9)
    monkeypatch.setattr(report, "failed_screenshots", lambda: failures)
    monkeypatch.setattr(
        report,
        "comments",
        lambda *args: [
            {
                "id": 42,
                "body": report.MARKER,
                "user": {"login": "visual-bot"},
            }
        ],
    )
    monkeypatch.setattr(
        report,
        "gh",
        lambda token, *args: (
            '{"login": "visual-bot"}'
            if args == ("api", "user")
            else "--attach"
        ),
    )
    patched = []
    monkeypatch.setattr(
        report, "patch_comment", lambda *args: patched.append(args)
    )
    monkeypatch.setattr(
        report,
        "write_comment",
        lambda *args, **kwargs: raise_unexpected_comment(),
    )
    monkeypatch.setattr(
        report, "remove_duplicate_comments", lambda *args: None
    )

    report.main()

    assert len(patched) == 1
    assert patched[0][1] == 42
    assert "9 screenshots failed" in patched[0][3]
    assert "complete set" in patched[0][3]
    assert "![Visual diff" not in patched[0][3]


def test_creates_visual_comment_with_inline_diff(monkeypatch, tmp_path):
    _set_ci_environment(monkeypatch)
    failures = _failures(tmp_path, 1)
    monkeypatch.setattr(report, "failed_screenshots", lambda: failures)
    monkeypatch.setattr(report, "comments", lambda *args: [])
    monkeypatch.setattr(
        report,
        "gh",
        lambda token, *args: (
            '{"login": "visual-bot"}'
            if args == ("api", "user")
            else "--attach"
        ),
    )
    calls = []
    monkeypatch.setattr(
        report,
        "write_comment",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        report, "remove_duplicate_comments", lambda *args: None
    )

    report.main()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs["edit_last"] is False
    assert args[4] == [failures[0] / "diff.png"]


def test_actions_token_updates_text_comment_without_attachments(
    monkeypatch, tmp_path
):
    _set_ci_environment(monkeypatch, attachment_token="")
    failures = _failures(tmp_path, 1)
    monkeypatch.setattr(report, "failed_screenshots", lambda: failures)
    monkeypatch.setattr(
        report,
        "comments",
        lambda *args: [
            {
                "id": 42,
                "body": report.MARKER,
                "user": {"login": "github-actions[bot]"},
            }
        ],
    )
    patched = []
    monkeypatch.setattr(
        report, "patch_comment", lambda *args: patched.append(args)
    )
    monkeypatch.setattr(
        report, "remove_duplicate_comments", lambda *args: None
    )

    report.main()

    assert patched[0][1] == 42
    assert patched[0][2] == "actions-token"
    assert "![Visual diff" not in patched[0][3]


def test_gh_comment_command_attaches_images(monkeypatch, tmp_path):
    image = tmp_path / "diff.png"
    image.write_bytes(b"png")
    recorded = []

    def fake_gh(token, *args):
        body = Path(args[args.index("--body-file") + 1]).read_text()
        recorded.append((token, args, body))

    monkeypatch.setattr(report, "gh", fake_gh)

    report.write_comment(
        "example/repo",
        "17",
        "bot-token",
        f"{report.MARKER}\n![diff]({image})\n",
        attachments=[image],
        edit_last=True,
    )

    token, args, body = recorded[0]
    assert token == "bot-token"
    assert args[:4] == ("pr", "comment", "17", "--repo")
    assert "--edit-last" in args
    assert args[args.index("--attach") + 1] == str(image)
    assert report.MARKER in body


def test_removes_older_visual_comments_after_bot_change(monkeypatch):
    monkeypatch.setattr(
        report,
        "comments",
        lambda *args: [
            {
                "id": 10,
                "body": report.MARKER,
                "user": {"login": "github-actions[bot]"},
            },
            {
                "id": 11,
                "body": report.MARKER,
                "user": {"login": "visual-bot"},
            },
            {
                "id": 12,
                "body": report.MARKER,
                "user": {"login": "visual-bot"},
            },
        ],
    )
    deleted = []
    monkeypatch.setattr(
        report, "gh", lambda token, *args: deleted.append((token, args))
    )

    report.remove_duplicate_comments(
        "example/repo", "17", "bot-token", "visual-bot", "actions-token"
    )

    assert deleted == [
        (
            "actions-token",
            (
                "api",
                "--method",
                "DELETE",
                "repos/example/repo/issues/comments/10",
            ),
        ),
        (
            "bot-token",
            (
                "api",
                "--method",
                "DELETE",
                "repos/example/repo/issues/comments/11",
            ),
        ),
    ]


def raise_unexpected_comment():
    raise AssertionError("a second PR comment was created")
