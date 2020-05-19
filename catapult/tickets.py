"""
Commands to interact with issue trackers
"""
from typing import List, Mapping

import invoke

from catapult import utils
from catapult.integrations.git import PullRequestState
from catapult.integrations.tracker import get_tracker
from catapult.projects import format_projects, list_projects


@invoke.task(
    default=True,
    help={
        "ticket_id": "Identifier of the ticket, eg `ch12345`, `SBDEV-2808`",
        "author": "include the author of the release/deploy",
        "sort": "comma-separated list of fields by which to sort the output, eg `timestamp,name`",
        "reverse": "reverse-sort the output",
        "only": "comma-separated list of apps to list",
        "permissions": "check if you have permission to release/deploy",
        "utc": "list timestamps in UTC instead of local timezone",
        "env": "show only deploys and for the specified environments (comma separated list)",
        "releases-only": "show only releases, no deploys",
    },
)
@utils.require_2fa
def find(
    _,
    ticket_id,
    author=False,
    sort=None,
    reverse=False,
    only=None,
    permissions=False,
    utc=False,
    env=None,
    releases_only=False,
):
    """
    What latest releases/deploys contain commits belonging to this ticket?
    """
    # TODO: link these commits back to app releases
    merged_commits = get_merged_commits_from_ticket(ticket_id)

    all_commits = []
    for repo_name, commits in merged_commits.items():
        for commit in commits:
            all_commits.append((repo_name, commit))

    num_commits = len(all_commits)
    utils.alert(
        f"Found {num_commits} commit{'s' if num_commits != 1 else ''} linked to {ticket_id}\n"
    )

    for i, (repo_name, commit) in enumerate(all_commits, start=1):
        utils.alert(f"Commit {i}/{num_commits}: {repo_name}: {commit}\n")
        projects = list_projects(
            contains=commit,
            only=only,
            permissions=permissions,
            utc=utc,
            env=env,
            releases_only=releases_only,
        )
        format_projects(
            projects,
            author=author,
            contains=True,
            sort=sort,
            reverse=reverse,
            permissions=permissions,
        )


def get_merged_commits_from_ticket(ticket_id: str) -> Mapping[str, List[str]]:
    # Returns a mapping of repo_name: [commits] for PRs linked to this ticket
    tracker = get_tracker()
    prs = tracker.get_linked_prs(ticket_id)
    if not prs:
        utils.warning("No PRs linked to this ticket\n")

    merged_pr_commits = {}
    for pr in prs:
        if pr.state is PullRequestState.OPEN:
            utils.warning(f"{pr.id} is still open\n")
        elif pr.state is PullRequestState.MERGED:
            merged_pr_commits.setdefault(pr.repo, []).append(pr.merge_commit)

    return merged_pr_commits


tickets = invoke.Collection("tickets", find)
