"""Summarize failed visual comparisons in one pull request comment."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

MARKER = "<!-- visual-regression-results -->"
RESULT_DIR = Path(__file__).resolve().parents[3] / "test-results" / "visual"
MAX_INLINE = 5
MAX_PREVIEW_FAILURES = 8


def failed_screenshots(result_dir=RESULT_DIR):
    return sorted(
        path.parent
        for path in result_dir.glob("*/actual.png")
        if path.is_file()
    )


def comment_body(failures, artifact_url, run_url, inline_diffs=()):
    count = len(failures)
    lines = [
        MARKER,
        "## Visual regression results",
        f"**{count} screenshot{'s' if count != 1 else ''} failed** in "
        f"the [Selenium run]({run_url}).",
        f"[Download the complete visual-test output]({artifact_url}) "
        "from the `visual-regression-diffs` Actions artifact.",
    ]
    if count > MAX_PREVIEW_FAILURES:
        lines.append(
            f"More than {MAX_PREVIEW_FAILURES} screenshots failed; "
            "open the artifact for the complete set."
        )
    else:
        lines.extend(["", "Failed screenshots:"])
        lines.extend(f"- `{path.name}`" for path in failures)
        if inline_diffs:
            lines.append("")
            for path in inline_diffs:
                lines.extend(
                    [
                        f"### Diff: `{path.parent.name}`",
                        f"![Visual diff for {path.parent.name}]({path})",
                        "",
                    ]
                )
    return "\n".join(lines).rstrip() + "\n"


def gh(token, *args):
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    result = subprocess.run(
        ["gh", *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def comments(repo, pr_number, token):
    found = []
    page = 1
    while True:
        batch = json.loads(
            gh(
                token,
                "api",
                f"repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}",
            )
        )
        found.extend(batch)
        if len(batch) < 100:
            return found
        page += 1


def bot_login(token, is_attachment_token):
    if not is_attachment_token:
        return "github-actions[bot]"
    return json.loads(gh(token, "api", "user"))["login"]


def write_comment(
    repo, pr_number, token, body, attachments=(), edit_last=False
):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md") as body_file:
        body_file.write(body)
        body_file.flush()
        args = ["pr", "comment", str(pr_number), "--repo", repo]
        if edit_last:
            args.append("--edit-last")
        args.extend(["--body-file", body_file.name])
        for path in attachments:
            args.extend(["--attach", str(path)])
        gh(token, *args)


def patch_comment(repo, comment_id, token, body):
    gh(
        token,
        "api",
        "--method",
        "PATCH",
        f"repos/{repo}/issues/comments/{comment_id}",
        "--raw-field",
        f"body={body}",
    )


def delete_comment(repo, comment_id, token):
    gh(
        token,
        "api",
        "--method",
        "DELETE",
        f"repos/{repo}/issues/comments/{comment_id}",
    )


def remove_duplicate_comments(repo, pr_number, token, login, action_token):
    marked = [
        item
        for item in comments(repo, pr_number, token)
        if MARKER in item.get("body", "")
    ]
    owned = [item for item in marked if item["user"]["login"] == login]
    if not owned:
        return
    keep_id = max(item["id"] for item in owned)
    for item in marked:
        author = item["user"]["login"]
        if author == login and item["id"] != keep_id:
            delete_comment(repo, item["id"], token)
        elif author == "github-actions[bot]" and token != action_token:
            delete_comment(repo, item["id"], action_token)


def main():
    failures = failed_screenshots()
    if not failures:
        print("No visual comparison output; skipping PR comment.")
        return

    repo = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]
    artifact_url = os.environ["VISUAL_ARTIFACT_URL"]
    run_url = (
        f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
        f"{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    )
    action_token = os.environ["GITHUB_TOKEN"]
    attachment_token = os.environ.get("VISUAL_REGRESSION_TOKEN", "")
    token = attachment_token or action_token
    login = bot_login(token, bool(attachment_token))
    all_comments = comments(repo, pr_number, token)
    marked = [item for item in all_comments if MARKER in item.get("body", "")]
    owned = [item for item in marked if item["user"]["login"] == login]
    previous = owned[-1] if owned else None
    if marked and not previous and not attachment_token:
        print(
            "A visual comment belongs to a different bot; keeping it and the artifact."
        )
        return

    can_attach = bool(attachment_token) and "--attach" in gh(
        token, "pr", "comment", "--help"
    )
    diffs = [
        path / "diff.png" for path in failures if (path / "diff.png").is_file()
    ]
    attachments = (
        diffs[:MAX_INLINE]
        if len(failures) <= MAX_PREVIEW_FAILURES and can_attach
        else []
    )
    if attachment_token and not can_attach:
        print(
            "Installed gh does not support --attach; linking the artifact instead."
        )
    if not attachment_token:
        print(
            "VISUAL_REGRESSION_TOKEN is unset; linking the artifact instead of inline images."
        )

    latest_owned_id = max(
        (
            item["id"]
            for item in all_comments
            if item["user"]["login"] == login
        ),
        default=None,
    )
    if attachments and (previous is None or previous["id"] == latest_owned_id):
        body = comment_body(failures, artifact_url, run_url, attachments)
        try:
            write_comment(
                repo,
                pr_number,
                token,
                body,
                attachments,
                edit_last=previous is not None,
            )
        except subprocess.CalledProcessError as error:
            print(f"Image attachment failed: {error.stderr.strip()}")
            all_comments = comments(repo, pr_number, token)
            owned = [
                item
                for item in all_comments
                if MARKER in item.get("body", "")
                and item["user"]["login"] == login
            ]
            previous = owned[-1] if owned else None
        else:
            print(f"Posted {len(attachments)} inline visual diffs.")
            remove_duplicate_comments(
                repo, pr_number, token, login, action_token
            )
            return

    body = comment_body(failures, artifact_url, run_url)
    if previous:
        patch_comment(repo, previous["id"], token, body)
        print(f"Updated visual regression comment {previous['id']}.")
    else:
        write_comment(repo, pr_number, token, body)
        print("Created visual regression comment.")
    remove_duplicate_comments(repo, pr_number, token, login, action_token)


if __name__ == "__main__":
    main()
