"""
Commands to manage deployments.
"""
import dataclasses
import logging
from datetime import datetime

import invoke
import pygit2 as git

from catapult import config, utils
from catapult.release import (
    ActionType,
    get_release,
    get_releases,
    list_releases,
    put_release,
)

LOG = logging.getLogger(__name__)


@invoke.task(
    help={
        "name": "identifies the project to deploy.",
        "env": "name of the environment where the app will be deployed",
        "version": "version to deploy",
        "bucket": "name of the bucket used to store the deploys",
        "dry": "prepare a release without committing it",
        "yes": "automatic yes to prompt",
        "rollback": "needed to start a rollback",
    },
    default=True,
)
@utils.require_2fa
def start(
    _, name, env, version=None, bucket=None, dry=False, yes=False, rollback=False
):
    """
    Deploy a release on an environment.
    """
    client = utils.s3_client()
    repo = utils.git_repo()

    if version is None:
        release = next(get_releases(client, name), None)

    else:
        release = get_release(client, name, int(version))

    if release is None:
        utils.fatal("Release not found")

    if bucket is None:
        bucket = utils.get_config()["deploy"][env]["s3_bucket"]

    last_deploy = next(get_releases(client, name, bucket=bucket), None)

    releases = list(
        get_releases(client, name, since=last_deploy.version if last_deploy else 0)
    )

    # the field commits is not present in all docuemnts as it was introduced
    # in a later version. if any of the releases doesn't track them, we'll
    # skip the commit filtering to avoid not showing commits in the changelog.
    if any(rel.commits is None for rel in releases):
        commits = None

    else:
        commits = [commit for rel in releases if rel.commits for commit in rel.commits]

    if last_deploy is None:
        # first deploy is always None
        changelog = utils.changelog(
            repo, release.commit, None, keep_only_commits=commits
        )

        changelog_text = changelog.short_text
        is_rollback = release.rollback

    else:
        # create a changelog from the latest deploy commit
        changelog = utils.changelog(
            repo,
            git.Oid(hex=release.commit),
            git.Oid(hex=last_deploy.commit),
            keep_only_commits=commits,
        )

        changelog_text = changelog.short_text
        is_rollback = changelog.rollback

    action_type = ActionType.automated if config.IS_CONCOURSE else ActionType.manual

    release = dataclasses.replace(
        release,
        changelog=changelog_text,
        timestamp=datetime.now(),
        author=utils.get_author(repo, git.Oid(hex=release.commit)),
        rollback=is_rollback,
        action_type=action_type,
        commits=commits,
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
                "Are you sure you want to start a rollback deployment?",
                style=utils.TextStyle.yellow,
            )

            if not ok:
                utils.fatal("Aborted!")

        ok = utils.confirm("Are you sure you want to start this deployment?")
        if not ok:
            utils.fatal("Aborted!")

    put_release(client, bucket, name, release)
    utils.success("Started new deployment :rocket:\n")


@invoke.task(
    help={
        "name": "project's name",
        "env": "name of the environment where the app will be deployed",
        "bucket": "name of the bucket used to store the deploys",
    }
)
@utils.require_2fa
def current(_, name, env, bucket=None):
    """
    Show current running version.
    """
    client = utils.s3_client()

    if bucket is None:
        bucket = utils.get_config()["deploy"][env]["s3_bucket"]

    last_deploy = next(get_releases(client, name, bucket=bucket), None)

    if last_deploy:
        utils.printfmt(last_deploy)

    else:
        utils.fatal("Release does not exist")


@invoke.task(
    help={
        "name": "project's name",
        "env": "name of the environment where the app will be deployed",
        "bucket": "name of the bucket used to store the deploys",
        "last": "return only the last n deploys",
        "contains": "commit hash or revision of a commit, eg `bcc31bc`, `HEAD`, `some_branch`",
        "utc": "list timestamps in UTC instead of local timezone",
    }
)
@utils.require_2fa
def ls(_, name, env, bucket=None, last=None, contains=None, utc=False):
    """
    Show all the project's deploys.
    """
    if bucket is None:
        bucket = utils.get_config()["deploy"][env]["s3_bucket"]

    list_releases(name, last, contains, bucket, utc=utc)


deploy = invoke.Collection("deploy", start, current, ls)
