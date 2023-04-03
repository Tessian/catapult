"""
Requires an API token.
https://app.shortcut.com/settings/account/api-tokens

This should be set as the env var `SHORTCUT_API_TOKEN`.
"""
import os
from typing import List

import requests

# from catapult.integrations.github import CLOSED_PR_STATES, PR_URL_RE, get_pr_details
from catapult.integrations.git import PullRequest, get_git
from catapult.integrations.tracker import BaseTracker

SC_STORY_ENDPOINT = "https://api.app.shortcut.com/api/v3/stories/{story_id}"


class Shortcut(BaseTracker):
    def get_linked_prs(self, issue_id: str) -> List[PullRequest]:
        git_provider = get_git()

        if issue_id.startswith("sc-"):
            issue_id = issue_id[3:]

        url = SC_STORY_ENDPOINT.format(story_id=issue_id)

        sc_token = os.environ["SHORTCUT_API_TOKEN"]
        headers = {"Content-Type": "application/json", "Shortcut-Token": sc_token}
        res = requests.get(url, headers=headers).json()

        prs = []
        for branch in res.get("branches", []):
            for pr in branch["pull_requests"]:
                pr_details = git_provider.get_pr_details(pr["url"])
                prs.append(pr_details)

        return prs
