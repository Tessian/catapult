"""
Requires a personal access token with `repo` scope.
https://github.com/settings/tokens

This should be set as the env var `GITHUB_API_TOKEN`.
"""
import os
import re

import requests

from catapult import utils
from catapult.integrations.git import BaseGit, PullRequest, PullRequestState

GH_ENDPOINT = "https://api.github.com/graphql"

PR_GRAPHQL_QUERY = """
query($owner: String!, $repo_name: String!, $pr_number: Int!) { 
    repository(owner: $owner, name: $repo_name) {
        pullRequest(number: $pr_number) {
            title
            state
            mergeCommit {
                oid
            }
        }
    }
}"""

PR_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/]+)/(?P<repo_name>[^/]+)/pull/(?P<pr_number>\d+)"
)


class GitHub(BaseGit):
    def get_pr_details(self, pr_identifier: str) -> PullRequest:
        parsed_pr_data = PR_URL_RE.fullmatch(pr_identifier)

        req_data = {
            "query": PR_GRAPHQL_QUERY,
            "variables": {
                "owner": parsed_pr_data["owner"],
                "repo_name": parsed_pr_data["repo_name"],
                "pr_number": int(parsed_pr_data["pr_number"]),
            },
        }
        gh_token = os.environ["GITHUB_API_TOKEN"]
        res = requests.post(
            GH_ENDPOINT, json=req_data, headers={"Authorization": f"bearer {gh_token}"}
        ).json()

        for error in res.get("errors", []):
            err_type = error.get("type")
            err_msg = error.get("message")
            utils.warning(f"{err_type}: {err_msg}\n")
            utils.warning(f"{error}\n")

        pr_details = res["data"]["repository"]["pullRequest"]

        merge_commit = None
        if pr_details["mergeCommit"] is not None:
            merge_commit = pr_details["mergeCommit"]["oid"]

        return PullRequest(
            id=pr_identifier,
            repo=parsed_pr_data["repo_name"],
            title=pr_details["title"],
            state=PullRequestState[pr_details["state"]],
            merge_commit=merge_commit,
        )
