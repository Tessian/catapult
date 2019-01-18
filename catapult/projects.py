"""
Commands to inspect projects.
"""
import logging

from botocore.exceptions import ClientError
import invoke

from catapult import utils
from catapult.release import _get_release as get_release, InvalidRelease

LOG = logging.getLogger(__name__)


@invoke.task(default=True)
@utils.require_2fa
def ls(_):
    """
    List all the projects managed with catapult.
    """
    client = utils.s3_client()

    projects = []

    config = utils.get_config()
    bucket = config["release"]["s3_bucket"]
    deploys = config["deploy"]

    resp = client.list_objects_v2(Bucket=bucket)
    for data in resp.get("Contents", []):
        name = data["Key"]

        projects.append(name)

    projects = sorted(projects)

    _projects = []

    for name in projects:
        try:
            release = get_release(client, bucket, name)
        except InvalidRelease:
            continue

        data = {
            "Name": name,
            "Latest Release": f"v{release.version} {release.timestamp} ({release.commit})",
        }

        for env_name, cfg in deploys.items():
            env_version, env_commit, env_timestamp = get_deployed_version(
                client, cfg["s3_bucket"], name
            )

            data[env_name.title()] = f"v{env_version} {env_timestamp} ({env_commit})"

        _projects.append(data)

    projects = _projects

    utils.printfmt(projects)


def get_deployed_version(client, bucket_name, project_name):
    try:
        deploy = get_release(client, bucket_name, project_name)

    except ClientError as e:
        if e.response["Error"]["Code"] == "AccessDenied":
            LOG.warning(f"Access denied on {bucket_name} for {project_name}: {str(e)}")
            return "???", "???", "???"
        raise

    except InvalidRelease:
        return "X", "X", "X"

    return deploy.version, deploy.commit, deploy.timestamp


projects = invoke.Collection("projects", ls)
