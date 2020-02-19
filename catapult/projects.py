"""
Commands to inspect projects.
"""
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from operator import itemgetter
from typing import NamedTuple, Optional

import invoke

from catapult import utils
from catapult.config import AWS_MFA_DEVICE
from catapult.release import ActionType, InvalidRelease, release_contains
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
    behind: int
    age: timedelta
    timestamp: datetime
    commit: str
    action_type: ActionType
    contains: Optional[bool]
    permission: Optional[bool]
    author: Optional[str]


@invoke.task(
    default=True,
    help={
        "author": "include the author of the release/deploy",
        "contains": "commit hash or revision of a commit, eg `bcc31bc`, `HEAD`, `some_branch`",
        "sort": "comma-separated list of fields by which to sort the output, eg `timestamp,name`",
        "reverse": "reverse-sort the output",
        "only": "comma-separated list of apps to list",
        "permissions": "check if you have permission to release/deploy",
    },
)
@utils.require_2fa
def ls(
    _,
    author=False,
    contains=None,
    sort=None,
    reverse=False,
    only=None,
    permissions=False,
):
    """
    List all the projects managed with catapult.

    Optionally pass a full SHA-1 hash of a commit in the current repo,
    and each release/deploy will be marked with 'Y' if it contains that
    commit, 'N' if it doesn't, or '?' if it can't be determined (eg
    perhaps the App belongs to another repo).
    """

    contains_oid = None
    repo = None

    optional_columns = {
        "author": bool(author),
        "contains": bool(contains),
        "permission": bool(permissions),
    }

    if contains:
        repo = utils.git_repo()
        contains_oid = utils.revparse(repo, contains)
        if contains_oid not in repo:
            raise Exception(f"Commit {contains_oid} does not exist in repo")

    valid_sort_keys = list(Project._fields)

    for column_name, show_column in optional_columns.items():
        if not show_column:
            valid_sort_keys.remove(column_name)

    sort_keys = [] if sort is None else sort.split(",")
    if any(sort_key not in valid_sort_keys for sort_key in sort_keys):
        raise Exception(
            f"Invalid sort key in {sort!r}. Valid sort keys: {valid_sort_keys}"
        )

    if only is not None:
        only = only.split(",")

    client = utils.s3_client()
    config = utils.get_config()
    release_bucket = config["release"]["s3_bucket"]
    deploys = config["deploy"]

    resp = client.list_objects_v2(Bucket=release_bucket)

    project_names = sorted(data["Key"] for data in resp.get("Contents", []))

    can_release = {}
    can_deploy = {}

    if permissions:
        iam_client = utils.iam_client()

        can_release = check_perms(iam_client, release_bucket, project_names)
        can_deploy = {
            env_name: check_perms(iam_client, cfg["s3_bucket"], project_names)
            for env_name, cfg in deploys.items()
        }

    _projects = []

    now = datetime.now(tz=timezone.utc)

    for name in project_names:
        if only and name not in only:
            continue

        try:
            release = get_release(client, release_bucket, name)
        except InvalidRelease:
            continue

        _projects.append(
            Project(
                name=name,
                version=release.version,
                behind=0,
                commit=release.commit,
                timestamp=release.timestamp,
                age=now - release.timestamp,
                type=ProjectType.release,
                contains=(
                    release_contains(repo, release, contains_oid, name)
                    if contains
                    else None
                ),
                env_name="",
                permission=can_release.get(name),
                action_type=release.action_type,
                author=release.author,
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
                    behind=release.version - deploy.version,
                    commit=deploy.commit,
                    timestamp=deploy.timestamp,
                    age=now - deploy.timestamp,
                    type=ProjectType.deploy,
                    env_name=env_name,
                    contains=(
                        release_contains(repo, deploy, contains_oid, name)
                        if contains
                        else None
                    ),
                    permission=can_deploy.get(env_name, {}).get(name),
                    action_type=deploy.action_type,
                    author=deploy.author,
                )
            )

    project_dicts = []
    for project in _projects:
        project_dict = project._asdict()
        for column_name, show_column in optional_columns.items():
            if not show_column:
                project_dict.pop(column_name)

        style = (
            utils.TextStyle.yellow
            if project_dict["type"] is ProjectType.release
            else utils.TextStyle.blue
        )
        project_dict["name"] = utils.Formatted(project_dict["name"], style)
        project_dict["type"] = utils.Formatted(project_dict["type"].name, style)
        project_dicts.append(project_dict)

    if sort_keys:
        project_dicts.sort(key=itemgetter(*sort_keys), reverse=reverse)

    utils.printfmt(project_dicts, tabular=True)


def check_perms(iam_client, bucket_name, project_names):

    region = utils.get_region_name()

    arn_to_project = {
        f"arn:aws:s3:::{bucket_name}/{project}": project for project in project_names
    }

    user_arn = AWS_MFA_DEVICE.replace(":mfa/", ":user/")

    perms = iam_client.simulate_principal_policy(
        PolicySourceArn=user_arn,
        ActionNames=["s3:PutObject"],
        ResourceArns=list(arn_to_project.keys()),
        ContextEntries=[
            {
                "ContextKeyName": "aws:multifactorauthpresent",
                "ContextKeyType": "boolean",
                "ContextKeyValues": ["true"],
            },
            {
                "ContextKeyName": "aws:requestedregion",
                "ContextKeyType": "string",
                "ContextKeyValues": [region],
            },
        ],
    )

    results = {}
    ev_results = perms["EvaluationResults"]

    for res in ev_results:
        arn = res["EvalResourceName"]
        project = arn_to_project[arn]

        if res["EvalDecision"] == "allowed":
            results[project] = True
        else:
            for rsr in res["ResourceSpecificResults"]:
                if rsr["EvalResourceName"] == arn:
                    results[project] = rsr["EvalResourceDecision"] == "allowed"
                    break

    return results


projects = invoke.Collection("projects", ls)
