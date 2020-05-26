from abc import ABC, abstractmethod
from enum import Enum
from typing import NamedTuple, Optional

from catapult import utils

GIT_HOST = None
GIT_CLASSES = {}


class PullRequestState(Enum):
    # This is a facsimile of https://developer.github.com/v4/enum/pullrequeststate/
    CLOSED = "CLOSED"
    MERGED = "MERGED"
    OPEN = "OPEN"


class PullRequest(NamedTuple):
    id: str
    repo: str
    title: str
    state: PullRequestState
    merge_commit: Optional[str]


class BaseGit(ABC):
    @abstractmethod
    def get_pr_details(self, pr_identifier: str) -> PullRequest:
        raise NotImplementedError

    def __init_subclass__(cls, **kwargs):
        GIT_CLASSES[cls.__name__] = cls


def get_git() -> BaseGit:
    global GIT_HOST

    if GIT_HOST:
        return GIT_HOST

    git_type = utils.get_config().get("git", {}).get("provider")
    if git_type not in GIT_CLASSES:
        utils.fatal(
            f"Unsupported git provider type {git_type!r} - try one of {sorted(GIT_CLASSES)!r}"
        )

    git_cls = GIT_CLASSES[git_type]
    GIT_HOST = git_cls()

    return GIT_HOST
