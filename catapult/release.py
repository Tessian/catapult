"""
Commands to manage releases.
"""
import dataclasses
import functools
import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum, auto
from typing import List, Optional

import invoke
import pygit2 as git
import pytz
from tzlocal import get_localzone

from catapult import config, utils

LOG = logging.getLogger(__name__)


class ActionType(Enum):
    manual = auto()
    automated = auto()


@dataclasses.dataclass
class Release:

    version: int
    commit: str
    version_id: str
    image: Optional[str]
    timestamp: datetime
    author: str
    changelog: str
    rollback: bool = False
    action_type: ActionType = ActionType.manual

    commits: Optional[List[str]] = None


class InvalidRelease(Exception):
    """
    Raised when the stored release is missing data or has an invalid format.
    """


@functools.lru_cache(maxsize=None)
def fetch_release(client, bucket, key, version_id=None) -> Release:
    """
    Fetches a release from a S3 object.

    Arguments:
        client (botocore.client.S3): client for AWS S3.
        bucket (str): bucket's name.
        key (str): object's key.
        version_id (str or None): version ID of the S3 object.
            If the `version_id` is `None`, it will return the latest release.

    Returns:
        Release or None: the release stored in the object.
    """
    extras = {}

    if version_id is not None:
        extras["VersionId"] = version_id

    try:
        resp = client.get_object(Bucket=bucket, Key=key, **extras)

    except client.exceptions.NoSuchKey:
        raise InvalidRelease(f"Key not found: {key}")

    try:
        body = json.load(resp["Body"])

    except json.JSONDecodeError as exc:
        raise InvalidRelease("Invalid JSON data") from exc

    try:
        version = body["version"]
        commit = body["commit"]
        image = body["image"]
        author = body["author"]
        rollback = body.get("rollback", False)
        action_type = ActionType[
            body.get("action_type", "automated" if author is None else "manual")
        ]
        commits = body.get("commits")

    except KeyError as exc:
        raise InvalidRelease(f"Missing property in JSON: {exc}")

    if "VersionId" not in resp:
        # files created when the bucket had the versioning disabled
        raise InvalidRelease("Object has no S3 VersionId")

    return Release(
        version=version,
        commit=commit,
        changelog=body.get("changelog", "<changelog unavailable>"),
        version_id=resp["VersionId"],
        image=image,
        timestamp=resp["LastModified"],
        author=author,
        rollback=rollback,
        action_type=action_type,
        commits=commits,
    )


@functools.lru_cache(maxsize=None)
def _get_versions(client, bucket, key):
    """
    Returns all the version IDs for a key ordered by last modified timestamp.
    """
    resp_iterator = client.get_paginator("list_object_versions").paginate(
        Bucket=bucket, Prefix=key
    )
    try:
        versions = [version for page in resp_iterator for version in page["Versions"]]
    except KeyError:
        utils.warning("No versions found\n")
        return ()

    obj_versions = sorted(versions, key=lambda v: v["LastModified"])
    versions = []

    for version in obj_versions:
        if version["Key"] != key:
            continue

        if version["VersionId"] is None or version["VersionId"] == "null":
            continue

        versions.append(version)

    return tuple(versions)


_DATETIME_MAX = pytz.utc.localize(datetime.max)


def _get_bucket():
    config = utils.get_config()
    print(config)
    if config:
        return config["release"]["s3_bucket"]
    return os.environ["CATAPULT_BUCKET_RELEASES"]


def get_releases(client, key, since=None, bucket=None):
    """
    Gets all the releases in the project's history.

    Arguments:
        client (botocore.client.S3): client for AWS S3.
        bucket (str): bucket's name.
        key (str): object's key.
        since (int or None): exclude version created before this version.

    Yield:
        Release a release in the project's history.
    """
    if bucket is None:
        bucket = _get_bucket()

    versions = sorted(
        _get_versions(client, bucket, key),
        key=lambda v: _DATETIME_MAX if v["IsLatest"] else v["LastModified"],
        reverse=True,
    )

    for version in versions:
        try:
            release = fetch_release(client, bucket, key, version["VersionId"])

        except InvalidRelease as exc:
            # skip invalid releases in object history
            LOG.warning(f"Invalid release object: {exc}")
            continue

        if since and release.version < since:
            break

        yield release


def get_release(client, key, version=None, bucket=None):
    """
    Fetches a specific release.

    Arguments:
        client (botocore.client.S3): client for AWS S3.
        bucket (str): bucket's name.
        key (str): object's key.
        version (int): version number.

    Returns:
        Release or None: the release identified by the given version.
            `None` if the version does not exist.
    """
    if bucket is None:
        bucket = _get_bucket()

    for release in get_releases(client, key, bucket=bucket):
        if release.version == version or version is None:
            return release

    return None


def put_release(client, bucket, key, release):
    """
    Upload a new release to S3.

    Arguments:
        client (botocore.client.S3): client for AWS S3.
        bucket (str): bucket's name.
        key (str): object's key.
        release (Release): release to upload.

    Returns:
        Release: uploaded release with the updated fields.
    """
    resp = client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(
            {
                "version": release.version,
                "commit": release.commit,
                "changelog": release.changelog,
                "image": release.image,
                "author": release.author,
                "rollback": release.rollback,
                "action_type": release.action_type.name,
                "commits": [str(commit) for commit in release.commits]
                if release.commits
                else None,
            }
        ),
    )

    return dataclasses.replace(
        release,
        version_id=resp["VersionId"],
        timestamp=pytz.utc.localize(datetime.utcnow()),
    )


def _get_image_id(ctx, commit: git.Oid, *, name: str, image_name: Optional[str]):
    image_base = utils.get_config()["release"]["docker_repository"]

    if image_name is None:
        image_prefix = utils.get_config()["release"]["docker_image_prefix"]
        image_name = f"{image_prefix}{name}"

    image = f"{image_base}/{image_name}:ref-{commit.hex}"

    LOG.info(f"Pulling {image}")
    res = ctx.run(f"docker pull {image}", hide="out")

    for line in res.stdout.split("\n"):
        if line.startswith("Digest:"):
            _, _, image_id = line.partition(":")
            return image_id.strip()

    return None


@invoke.task(help={"name": "project's name", "profile": "name of AWS profile to use"})
@utils.require_2fa
def current(_, name, profile=None):
    """
    Show current release.
    """
    release = next(get_releases(utils.s3_client(profile), name), None)

    if release:
        utils.printfmt(release)

    else:
        utils.fatal("Release does not exist")


@invoke.task(
    help={
        "name": "project's name",
        "version": "release's version",
        "profile": "name of AWS profile to use",
    }
)
@utils.require_2fa
def get(_, name, version, profile=None):
    """
    Show the release.
    """
    release = get_release(utils.s3_client(profile), name, int(version))

    if release:
        utils.printfmt(release)

    else:
        utils.fatal("Release does not exist")


@invoke.task(
    help={
        "name": "project's name",
        "last": "return only the last n releases",
        "contains": "commit hash or revision of a commit, eg `bcc31bc`, `HEAD`, `some_branch`",
        "utc": "list timestamps in UTC instead of local timezone",
        "profile": "name of AWS profile to use",
    }
)
@utils.require_2fa
def ls(_, name, last=None, contains=None, utc=False, profile=None):
    """
    Show all the project's releases.
    """
    list_releases(name, last, contains, utc=utc, profile=profile)


def list_releases(name, last, contains, bucket=None, utc=False, profile=None):
    repo = None
    contains_oid = None

    if contains:
        repo = utils.git_repo()
        contains_oid = utils.revparse(repo, contains)
        if contains_oid not in repo:
            raise Exception(f"Commit {contains_oid} does not exist in repo")

    releases = get_releases(utils.s3_client(profile), name, bucket=bucket)

    release_data = []
    now = datetime.now(tz=timezone.utc)
    localzone = get_localzone()
    last = int(last) if last else None

    for i, rel in enumerate(releases):
        if i == last:
            break

        timestamp_utc = rel.timestamp
        timestamp = timestamp_utc if utc else timestamp_utc.astimezone(localzone)

        release_dict = {
            "version": rel.version,
            "commit": rel.commit,
            "timestamp": timestamp,
            "age": now - timestamp_utc,
            "author": rel.author,
            "rollback": rel.rollback,
            "action_type": rel.action_type,
        }
        if contains:
            release_dict["contains"] = release_contains(repo, rel, contains_oid, name)
        release_data.append(release_dict)

    utils.printfmt(release_data, tabular=True)


@invoke.task(
    help={
        "name": "identifies the project to release.",
        "commit": "git ref to build from.",
        "version": "new version",
        "image-id": "ID of the docker image to release.",
        "has-image": "Whether the deployment includes a docker image.",
        "image-name": "name of the image to release (default to name)",
        "dry": "prepare a release without committing it",
        "yes": "Automatic yes to prompt",
        "rollback": "needed to start a rollback",
        "filter-files-path": "keep only the commits that touched the files listed in this file.",
        "profile": "name of AWS profile to use",
    },
    default=True,
)
@utils.require_2fa
def new(
    ctx,
    name,
    commit=None,
    version=None,
    dry=False,
    yes=False,
    has_image=True,
    image_name=None,
    image_id=None,
    rollback=False,
    filter_files_path=None,
    profile=None,
):
    """
    Create a new release.
    """
    repo = utils.git_repo()

    client = utils.s3_client(profile)
    latest = next(get_releases(client, name), None)
    latest_oid = git.Oid(hex=latest.commit) if latest else None

    if commit is None:
        commit = "HEAD"

    commit_oid = utils.revparse(repo, commit)

    if version is None:
        # create next version
        version = 1 if latest is None else latest.version + 1

    else:
        version = int(version)

    if image_id is None and has_image is True:
        image_id = _get_image_id(ctx, commit_oid, name=name, image_name=image_name)

        if image_id is None:
            utils.fatal("Image not found")

    keep_only_files = None
    if filter_files_path:
        with open(filter_files_path) as fp:
            keep_only_files = [line.strip() for line in fp]

    changelog = utils.changelog(
        repo, commit_oid, latest_oid, keep_only_files=keep_only_files
    )

    action_type = ActionType.automated if config.IS_CONCOURSE else ActionType.manual

    release = Release(
        version=version,
        commit=commit_oid.hex,
        changelog=changelog.truncated_text,
        version_id="",
        image=image_id,
        timestamp=datetime.now(),
        author=utils.get_author(repo, commit_oid),
        rollback=changelog.rollback,
        action_type=action_type,
        commits=[commit.hex for commit in changelog.logs],
    )

    utils.printfmt(release)

    if dry:
        return

    if release.rollback:
        utils.warning("This is a rollback! :warning:\n")

        if not rollback:
            utils.warning("Missing flag --rollback\n")
            utils.fatal("Aborted!")

    if not yes:

        if release.rollback:
            ok = utils.confirm(
                "Are you sure you want to create a rollback release?",
                style=utils.TextStyle.yellow,
            )

            if not ok:
                utils.fatal("Aborted!")

        ok = utils.confirm("Are you sure you want to create this release?")
        if not ok:
            utils.fatal("Aborted!")

    put_release(client, _get_bucket(), name, release)

    utils.success("Created new release :tada:\n")


@invoke.task(
    help={
        "name": "identifies the project to release.",
        "commit": "git ref of the release to look for.",
        "profile": "name of AWS profile to use",
    }
)
@utils.require_2fa
def find(_, name, commit=None, profile=None):
    """
    Find the first release containing a specific commit.
    """
    if commit is None:
        commit = "HEAD"

    repo = utils.git_repo()
    oid = utils.revparse(repo, commit)

    client = utils.s3_client(profile)

    releases = {release.commit: release for release in get_releases(client, name)}

    release = None
    for log in utils.git_log(repo):
        if log.hex in releases:
            release = releases[log.hex]

        if oid.hex == log.hex:
            break

    if release:
        utils.printfmt(release)

    else:
        LOG.error("Commit not released yet")


@invoke.task(
    help={
        "name": "The name of the project whose versions to use",
        "range": "A range in the format <old>..<new>.",
        "resolve": "transform the version range into a valid git log range",
        "verbose": "Produce verbose git log output",
        "profile": "name of AWS profile to use",
    }
)
@utils.require_2fa
def log(_, name, range, resolve=False, verbose=False, profile=None):
    """
    Show git log between versions and/or commits.

    This resolves catapult versions (eg `v123`) into git commits, in
    addition to anything that git can map to a single commit, eg
    `fc20299e`, `my_branch`, `some_tag`.
    """
    repo = utils.git_repo()

    client = utils.s3_client(profile)

    lx, _, rx = range.partition("..")

    def resolve_range(ref):
        if ref.startswith("v") and ref[1:].isdigit():
            release = get_release(client, name, int(ref[1:]))
            ref = release.commit
        return utils.revparse(repo, ref)

    start = resolve_range(lx)
    end = resolve_range(rx)

    if resolve:
        text = f"{start.hex}...{end.hex}"

    else:
        changelog = utils.changelog(repo, end, start)
        text = changelog.text if verbose else changelog.short_text

    print(text)


def release_contains(
    repo: git.Repository, release: Release, commit_oid: git.Oid, name: str
):
    if not release.commit:
        utils.warning(f"{name} has a null commit ref\n")
        return "?"

    release_oid = git.Oid(hex=release.commit)
    try:
        in_release = utils.commit_contains(repo, release_oid, commit_oid)
    except utils.CommitNotFound as e:
        utils.warning(f"Error: [{repr(e)}], Project: [{name}]\n")
        in_release = "?"

    return in_release


release = invoke.Collection("release", current, ls, new, find, get, log)
