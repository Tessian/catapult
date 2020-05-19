from abc import ABC, abstractmethod
from typing import List

from catapult import utils
from catapult.integrations.git import PullRequest

TRACKER = None

TRACKER_CLASSES = {}


class BaseTracker(ABC):
    @abstractmethod
    def get_linked_prs(self, issue_id: str) -> List[PullRequest]:
        raise NotImplementedError

    def __init_subclass__(cls, **kwargs):
        TRACKER_CLASSES[cls.__name__] = cls


def get_tracker() -> BaseTracker:
    global TRACKER

    if TRACKER:
        return TRACKER

    tracker_type = utils.get_config().get("issue_tracker", {}).get("provider")

    if tracker_type not in TRACKER_CLASSES:
        utils.fatal(
            f"Unsupported tracker type {tracker_type} - try one of {sorted(TRACKER_CLASSES)!r}"
        )

    tracker_cls = TRACKER_CLASSES[tracker_type]
    TRACKER = tracker_cls()

    return TRACKER
