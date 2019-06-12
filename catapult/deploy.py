"""
Commands to manage deployments.
"""
from datetime import datetime
import dataclasses
import sys

import invoke
import logging

from catapult.release import get_releases, get_release, put_release
from catapult import utils

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
        LOG.critical("Release not found")
        sys.exit(1)

    if bucket is None:
        bucket = utils.get_config()["deploy"][env]["s3_bucket"]

    last_deploy = next(get_releases(client, name, bucket=bucket), None)
    if last_deploy is None:
        # first deploy is always None
        changelog_text = release.changelog
        is_rollback = release.rollback

    else:
        # create a changelog from the latest deploy commit
        changelog = utils.changelog(repo, release.commit, last_deploy.commit)

        changelog_text = changelog.text
        is_rollback = changelog.rollback

    release = dataclasses.replace(
        release,
        changelog=changelog_text,
        timestamp=datetime.now(),
        author=utils.get_author(repo),
        rollback=is_rollback,
    )

    utils.printfmt(release)

    if dry:
        return

    if release.rollback:
        utils.warning("This is a rollback! :warning:\n")

        if not rollback:
            utils.warning("Missing flag --rollback\n")
            utils.error("Aborted!\n")
            sys.exit(1)

    if not yes:

        if release.rollback:
            ok = utils.confirm(
                "Are you sure you want to start a rollback deployment?",
                style=utils.TextStyle.warning,
            )

            if not ok:
                utils.error("Aborted!\n")
                sys.exit(1)

        ok = utils.confirm("Are you sure you want to start this deployment?")
        if not ok:
            utils.error("Aborted!\n")
            sys.exit(1)

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
        LOG.critical("Release does not exist")
        sys.exit(1)


deploy = invoke.Collection("deploy", start, current)
