"""
Requires an API token.
https://app.clubhouse.io/settings/account/api-tokens

This should be set as the env var `CH_TOKEN`.
"""
import os
from typing import List

import requests

# from catapult.integrations.github import CLOSED_PR_STATES, PR_URL_RE, get_pr_details
from catapult.integrations.git import PullRequest, get_git
from catapult.integrations.tracker import BaseTracker

CH_STORY_ENDPOINT = (
    "https://api.clubhouse.io/api/v3/stories/{story_id}?token={ch_token}"
)


class Clubhouse(BaseTracker):
    def get_linked_prs(self, issue_id: str) -> List[PullRequest]:
        git_provider = get_git()
        if issue_id.startswith("ch"):
            issue_id = issue_id[2:]
        url = CH_STORY_ENDPOINT.format(
            story_id=issue_id, ch_token=os.environ["CH_TOKEN"]
        )
        res = requests.get(url, headers={"Content-Type": "application/json"}).json()

        prs = []
        for branch in res.get("branches", []):
            for pr in branch["pull_requests"]:
                pr_details = git_provider.get_pr_details(pr["url"])
                prs.append(pr_details)

        return prs
