import enum
import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timedelta
from functools import partial
from typing import Any, List, Mapping

import boto3
import colorama
import dataclasses
import emoji
import pygit2 as git
import termcolor
import toml
import wrapt
from tabulate import tabulate

from catapult import config

LOG = logging.getLogger(__name__)

colorama.init()


_SESSION = None

try:
    with open(config.CATAPULT_SESSION, "rb") as f:
        _SESSION = json.load(f)

    expiration = _SESSION["aws_session_expiration"]
    _SESSION["aws_session_expiration"] = datetime.strptime(
        expiration, "%Y-%m-%dT%H:%M:%S"
    )

    if _SESSION["aws_session_expiration"] < datetime.utcnow():
        LOG.warning("Stored session has expired")
        _SESSION = None

except Exception as exc:
    LOG.error("Cannot load catapult session: " + str(exc))
    pass


def format_timedelta(td: timedelta):

    units = [
        ("second", 60),
        ("minute", 60),
        ("hour", 24),
        ("day", 365),  # near enough
        ("year", None),
    ]

    value = int(td.total_seconds())
    unit = units[0][0]

    for unit, multiplier in units:
        if multiplier is None or abs(value) < multiplier:
            break
        value //= multiplier

    return f"{value} {unit}{'s' if value != 1 else ''}"


class JsonEncoder(json.JSONEncoder):
    def default(self, o):  # pylint: disable=method-hidden
        if isinstance(o, datetime):
            return o.isoformat()

        if isinstance(o, timedelta):
            return format_timedelta(o)

        elif dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)

        return super().default(o)


class TextStyle(enum.Enum):
    """
    Defines different styles for catapult messages.
    """

    default = (None, None, [])
    success = ("green", None, [])
    warning = ("yellow", None, [])
    error = ("red", None, ["bold"])

    def __init__(self, fg, bg, attrs):
        self.fg = fg
        self.bg = bg
        self.attrs = list(attrs)


def confirm(prompt, style=TextStyle.default):
    _print(f"{prompt} [y/N] ", style)

    answer = input()

    return answer.lower() == "y"


def _print(text, style):
    termcolor.cprint(
        emoji.emojize(text, use_aliases=True),
        style.fg,
        style.bg,
        attrs=style.attrs,
        end="",
    )


success = partial(_print, style=TextStyle.success)
warning = partial(_print, style=TextStyle.warning)
error = partial(_print, style=TextStyle.error)


def to_human(data):
    if isinstance(data, list):
        text = "\n".join(to_human(v) for v in data)

    elif dataclasses.is_dataclass(data):
        table = [
            [f.name, getattr(data, f.name)]
            for i, f in enumerate(dataclasses.fields(data))
        ]

        text = tabulate(table, [], tablefmt="simple")

    elif isinstance(data, dict):
        table = [[h, data[h]] for h in sorted(data.keys())]

        text = tabulate(table, [], tablefmt="simple")

    elif isinstance(data, timedelta):
        text = format_timedelta(data)

    else:
        text = str(data)

    return text


def to_human_tabular(rows: List[Mapping[str, Any]]):
    formatted_rows = [
        {key: "" if value is None else to_human(value) for key, value in row.items()}
        for row in rows
    ]

    return tabulate(formatted_rows, headers="keys", tablefmt="grid")


FORMATTERS = {
    "human": to_human,
    "human_tabular": to_human_tabular,
    "json": partial(json.dumps, indent=2, sort_keys=True, cls=JsonEncoder),
}


def printfmt(data, tabular=False):
    fmt_name = os.environ.get("CATAPULT_FORMAT")

    if fmt_name is None:
        if os.isatty(sys.stdout.fileno()):
            fmt_name = "human"

        else:
            fmt_name = "json"

    if tabular and fmt_name == "human":
        fmt_name = "human_tabular"

    fmt = FORMATTERS.get(fmt_name)
    if fmt is None:
        LOG.critical("invalid formatter: {fmt_name}")
        sys.exit(1)

    sys.stdout.write(fmt(data) + "\n")


def _aws_session(profile=config.AWS_PROFILE):
    if _SESSION:
        session = boto3.session.Session(
            aws_access_key_id=_SESSION["aws_access_key_id"],
            aws_secret_access_key=_SESSION["aws_secret_access_key"],
            aws_session_token=_SESSION["aws_session_token"],
        )

    else:
        session = boto3.session.Session(profile_name=profile)

    return session


def s3_client(profile=config.AWS_PROFILE):
    """
    Creates a S3 client using the given profile.

    Arguments:
        profile (str): profile's name.

    Returns:
        botocore.client.S3: S3 client.
    """
    session = _aws_session(profile)

    return session.client("s3")


def sts_client(profile=config.AWS_PROFILE):
    """
    Creates a STS client using the given profile.

    Arguments:
        profile (str): profile's name.

    Returns:
        botocore.client.STS: STS client.
    """
    session = _aws_session(profile)

    return session.client("sts")


def iam_client(profile=config.AWS_PROFILE):
    """
    Creates a IAM client using the given profile.

    Arguments:
        profile (str): profile's name.

    Returns:
        botocore.client.STS: STS client.
    """
    session = _aws_session(profile)

    return session.client("iam")


def git_repo():
    """
    Creates a instance of `Repository` for the repo
    in the current directory. It tries to find the `.git`
    directory in any of the parent paths.
    """
    path = pathlib.Path(config.GIT_REPO).resolve()

    while True:
        git_path = path.joinpath(".git")

        # pylint: disable=no-member
        if git_path.is_dir():
            logging.debug(f"Using repository: {git_path}")
            return git.Repository(str(git_path))

        if path.parent == path:
            # reached '/'
            logging.error(f"Cannot find git repository")
            return None

        path = path.parent


def get_author(repo):
    # use git user email as release's author
    emails = list(repo.config.get_multivar("user.email"))

    if not emails:
        LOG.critical("Cannot find author email")
        return None

    return emails[0]


def commit_contains(
    repo: git.Repository, commit: git.Oid, maybe_ancestor: git.Oid
) -> bool:
    # Does `commit` contain `maybe_ancestor`?

    if commit == maybe_ancestor:
        return True

    return repo.descendant_of(commit, maybe_ancestor)


class InvalidRange(Exception):
    pass


def git_log(repo, *, start=None, end=None):
    # pylint: disable=no-member
    start = git.Oid(hex=start) if start else repo.head.target

    for commit in repo.walk(start, git.GIT_SORT_TOPOLOGICAL):
        yield commit

        if commit.hex == end:
            break

    else:
        if end is not None:
            raise InvalidRange()


@dataclasses.dataclass
class Changelog:

    logs: List[git.Commit]
    rollback: bool

    @property
    def text(self):
        text = []

        for log in self.logs:
            commit_time = datetime.fromtimestamp(log.commit_time)

            text.append(f"commit {log.hex}")
            text.append(f"Author: {log.author.name} <{log.author.email}>")
            text.append(f"Date:   {commit_time}")
            text.append("")
            text.extend("    " + line for line in log.message.split("\n"))
            text.append("")

        return "\n".join(text)


def changelog(repo, latest, prev):
    rollback = False

    try:
        logs = list(git_log(repo=repo, start=latest, end=prev))[:-1]

    except InvalidRange:
        logs = reversed(list(git_log(repo=repo, start=prev, end=latest)))

        rollback = True

    return Changelog(logs=logs, rollback=rollback)


def _refresh_session():
    global _SESSION

    if _SESSION:
        return

    if not config.AWS_MFA_DEVICE:
        return

    sts = sts_client()

    token_code = input("MFA Token Code: ")

    resp = sts.get_session_token(
        DurationSeconds=36000, SerialNumber=config.AWS_MFA_DEVICE, TokenCode=token_code
    )
    creds = resp["Credentials"]

    expiration = creds["Expiration"]
    _SESSION = {
        "aws_access_key_id": creds["AccessKeyId"],
        "aws_secret_access_key": creds["SecretAccessKey"],
        "aws_session_token": creds["SessionToken"],
        "aws_session_expiration": expiration,
    }

    with open(config.CATAPULT_SESSION, "w") as f:
        data = _SESSION.copy()
        data["aws_session_expiration"] = expiration.strftime("%Y-%m-%dT%H:%M:%S")

        json.dump(data, f)


@wrapt.decorator
def require_2fa(wrapped, instanct, args, kwargs):
    _refresh_session()

    return wrapped(*args, **kwargs)


CONFIG = None


def get_config():
    """
    Loads catapult configuration from a TOML file.
    """
    global CONFIG

    if CONFIG is None:
        path = os.path.dirname(git_repo().path.rstrip("/"))
        path = os.path.join(path, ".catapult.toml")

        with open(path, "r") as fp:
            CONFIG = toml.load(fp)

    return CONFIG
