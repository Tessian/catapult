"""
Commands to inspect projects.
"""
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from operator import itemgetter
from typing import NamedTuple, Optional

import invoke
import pygit2 as git

from catapult import utils
from catapult.release import InvalidRelease, Release
from catapult.release import _get_release as get_release

LOG = logging.getLogger(__name__)


class ProjectType(Enum):
    release = "release"
    deploy = "deploy"


class Project(NamedTuple):
    name: str
    type: ProjectType
    env_name: str
    version: int
    age: timedelta
    timestamp: datetime
    commit: str
    contains: Optional[bool]


@invoke.task(
    default=True,
    help={
        "contains": "Full SHA-1 hash of a commit in the current repo",
        "sort": "comma-separated list of fields by which to sort the output, eg `timestamp,name`",
        "reverse": "reverse-sort the output",
        "only": "comma-separated list of apps to list",
    },
)
@utils.require_2fa
def ls(_, contains=None, sort=None, reverse=False, only=None):
    """
    List all the projects managed with catapult.

    Optionally pass a full SHA-1 hash of a commit in the current repo,
    and each release/deploy will be marked with 'Y' if it contains that
    commit, 'N' if it doesn't, or '?' if it can't be determined (eg
    perhaps the App belongs to another repo).
    """

    contains_oid = None
    repo = None

    if contains:
        contains_oid = git.Oid(hex=contains)
        repo = utils.git_repo()
        if contains_oid not in repo:
            raise Exception(f"Commit {contains_oid} does not exist in repo")

    valid_sort_keys = list(Project._fields)
    if not contains:
        valid_sort_keys.remove("contains")

    sort_keys = [] if sort is None else sort.split(",")
    if any(sort_key not in valid_sort_keys for sort_key in sort_keys):
        raise Exception(
            f"Invalid sort key in {sort!r}. Valid sort keys: {valid_sort_keys}"
        )

    if only is not None:
        only = only.split(",")

    client = utils.s3_client()
    config = utils.get_config()
    bucket = config["release"]["s3_bucket"]
    deploys = config["deploy"]

    resp = client.list_objects_v2(Bucket=bucket)

    project_names = sorted(data["Key"] for data in resp.get("Contents", []))

    _projects = []

    now = datetime.now(tz=timezone.utc)

    for name in project_names:
        if only and name not in only:
            continue

        try:
            release = get_release(client, bucket, name)
        except InvalidRelease:
            continue

        _projects.append(
            Project(
                name=name,
                version=release.version,
                commit=release.commit,
                timestamp=release.timestamp,
                age=now - release.timestamp,
                type=ProjectType.release,
                contains=release_contains(repo, release, contains_oid, name)
                if contains
                else None,
                env_name="",
            )
        )

        for env_name, cfg in deploys.items():
            try:
                deploy = get_release(client, cfg["s3_bucket"], name)
            except InvalidRelease:
                continue

            _projects.append(
                Project(
                    name=name,
                    version=deploy.version,
                    commit=deploy.commit,
                    timestamp=deploy.timestamp,
                    age=now - deploy.timestamp,
                    type=ProjectType.deploy,
                    env_name=env_name,
                    contains=release_contains(repo, deploy, contains_oid, name)
                    if contains
                    else None,
                )
            )

    project_dicts = []
    for project in _projects:
        project_dict = project._asdict()
        if not contains:
            project_dict.pop("contains")
        project_dict["type"] = project_dict["type"].name
        project_dicts.append(project_dict)

    if sort_keys:
        project_dicts.sort(key=itemgetter(*sort_keys), reverse=reverse)

    utils.printfmt(project_dicts, tabular=True)


def release_contains(
    repo: git.Repository, release: Release, commit_oid: git.Oid, name: str
):
    release_oid = git.Oid(hex=release.commit)
    try:
        in_release = (
            "Y" if utils.commit_contains(repo, release_oid, commit_oid) else "N"
        )
    except git.GitError as e:
        LOG.warning(f"Repo: [{repo.workdir}], Error: [{repr(e)}], Project: [{name}]")
        in_release = "?"

    return in_release


projects = invoke.Collection("projects", ls)
