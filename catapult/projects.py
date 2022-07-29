"""
Commands to inspect projects.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, NamedTuple, Optional

import invoke
from tzlocal import get_localzone

from catapult import utils
from catapult.release import ActionType, InvalidRelease, fetch_release, release_contains

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
        "sort": (
            "comma-separated list of fields by which to sort the output, eg `timestamp,name`. "
            "Prepend a field name with `!` to reverse the sorting by that field."
        ),
        "only": "regex to filter listed apps",
        "permissions": "check if you have permission to release/deploy",
        "utc": "list timestamps in UTC instead of local timezone",
        "env": "show only deploys and for the specified environments (comma separated list)",
        "releases-only": "show only releases, no deploys",
        "profile": "name of AWS profile to use",
    },
)
@utils.require_2fa
def ls(
    _,
    author=False,
    contains=None,
    sort=None,
    only=None,
    permissions=False,
    utc=False,
    env=None,
    releases_only=False,
    profile=None,
):
    """
    List all the projects managed with catapult.

    Optionally pass a full SHA-1 hash of a commit in the current repo,
    and each release/deploy will be marked with 'Y' if it contains that
    commit, 'N' if it doesn't, or '?' if it can't be determined (eg
    perhaps the App belongs to another repo).
    """

    projects_ = list_projects(
        contains=contains,
        only=only,
        permissions=permissions,
        utc=utc,
        env=env,
        releases_only=releases_only,
        profile=profile,
    )
    format_projects(projects_, author, contains, sort, permissions)


def sorted_multi(collection, sort_spec: str, valid_sort_keys: List[str]):
    class reversor:
        def __init__(self, obj):
            self.obj = obj

        def __eq__(self, other):
            return other.obj == self.obj

        def __lt__(self, other):
            return other.obj < self.obj

    sort_keys = []

    if sort_spec is not None:
        for key in sort_spec.split(","):
            rev = False
            if key.startswith("!"):
                key = key[1:]
                rev = True
            sort_keys.append((key, rev))

    if any(sort_key not in valid_sort_keys for sort_key, rev in sort_keys):
        raise Exception(
            f"Invalid sort key in {sort_spec!r}. Valid sort keys: {valid_sort_keys}"
        )

    return sorted(
        collection,
        key=lambda item: tuple(
            reversor(item[k]) if rev else item[k] for k, rev in sort_keys
        ),
    )


def format_projects(_projects: List[Project], author, contains, sort, permissions):
    optional_columns = {
        "author": bool(author),
        "contains": bool(contains),
        "permission": bool(permissions),
    }

    valid_sort_keys = list(Project._fields)

    for column_name, show_column in optional_columns.items():
        if not show_column:
            valid_sort_keys.remove(column_name)

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

    project_dicts = sorted_multi(
        project_dicts, sort_spec=sort, valid_sort_keys=valid_sort_keys
    )

    utils.printfmt(project_dicts, tabular=True)


def list_projects(
    contains, only, permissions, utc, env, releases_only, profile
) -> List[Project]:

    contains_oid = None
    repo = None

    if contains:
        repo = utils.git_repo()
        contains_oid = utils.revparse(repo, contains)
        if contains_oid not in repo:
            raise Exception(f"Commit {contains_oid} does not exist in repo")

    if only is not None:
        only = re.compile(only)

    if env is not None:
        env = set(env.split(","))

    client = utils.s3_client(profile)
    config = utils.get_config()
    release_bucket = config["release"]["s3_bucket"]
    deploys = config["deploy"]

    resp = client.list_objects_v2(Bucket=release_bucket)

    project_names = sorted(data["Key"] for data in resp.get("Contents", []))

    can_release = {}
    can_deploy = {}

    if permissions:
        iam_client = utils.iam_client(profile)

        can_release = check_perms(iam_client, release_bucket, project_names, profile)
        can_deploy = {
            env_name: check_perms(iam_client, cfg["s3_bucket"], project_names, profile)
            for env_name, cfg in deploys.items()
        }

    _projects = []

    now = datetime.now(tz=timezone.utc)
    localzone = get_localzone()

    for name in project_names:
        if only and only.search(name) is None:
            continue

        try:
            release = fetch_release(client, release_bucket, name)
        except InvalidRelease:
            continue

        timestamp_utc = release.timestamp
        timestamp = timestamp_utc if utc else timestamp_utc.astimezone(localzone)

        if releases_only or env is None:
            _projects.append(
                Project(
                    name=name,
                    version=release.version,
                    behind=0,
                    commit=release.commit,
                    timestamp=timestamp,
                    age=now - timestamp_utc,
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

        if releases_only:
            continue

        for env_name, cfg in deploys.items():
            try:
                deploy = fetch_release(client, cfg["s3_bucket"], name)
            except InvalidRelease:
                continue

            timestamp_utc = deploy.timestamp
            timestamp = timestamp_utc if utc else timestamp_utc.astimezone(localzone)

            if not env or env_name in env:
                _projects.append(
                    Project(
                        name=name,
                        version=deploy.version,
                        behind=release.version - deploy.version,
                        commit=deploy.commit,
                        timestamp=timestamp,
                        age=now - timestamp_utc,
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

    return _projects


def assumed_role_to_role(caller_arn: str) -> str:
    """
    If it's an assumed role, we expect the caller ARN to look something like:

        arn:aws:sts::000000000000:assumed-role/<assumed-role-name>/<actual.username>

    We want to turn this into something like:

        arn:aws:sts::000000000000:role/<assumed-role-name>

    TODO: Find out if there is a proper way to do this
    """
    arn_parts = caller_arn.split(":")

    if arn_parts[:3] != ["arn", "aws", "sts"]:
        utils.fatal(f"Can't normalise caller ARN: {caller_arn}")

    user_parts = arn_parts[5].split("/")

    if user_parts[0] != "assumed-role":
        return caller_arn

    user_parts = ["role", user_parts[1]]
    user_str = "/".join(user_parts)
    arn_parts[5] = user_str
    return ":".join(arn_parts)


def check_perms(iam_client, bucket_name, project_names, profile):

    region = utils.get_region_name(profile)
    if region is None:
        utils.fatal(
            "Can't check permissions with no region set. Try setting in ~/.aws/credentials"
        )

    caller_identity = utils.get_caller_identity(profile)
    caller_arn = caller_identity["Arn"]

    # We need to do this because you can't call SimulatePrincipalPolicy on an assumed role.
    # See https://stackoverflow.com/questions/52941478/simulate-principal-policy-using-assumed-role
    caller_arn = assumed_role_to_role(caller_arn)

    arn_to_project = {
        f"arn:aws:s3:::{bucket_name}/{project}": project for project in project_names
    }

    perms = iam_client.simulate_principal_policy(
        PolicySourceArn=caller_arn,
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
