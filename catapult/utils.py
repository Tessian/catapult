import dataclasses
import enum
import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timedelta
from functools import partial, singledispatch
from typing import Any, List, Mapping, Optional

import boto3
import colorama
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
        LOG.debug("Stored session has expired")
        _SESSION = None

except Exception as exc:
    LOG.debug("Cannot load catapult session: " + str(exc))
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

        elif isinstance(o, Formatted):
            return str(o)

        elif isinstance(o, enum.Enum):
            return o.name

        elif dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)

        return super().default(o)


class TextStyle(enum.Enum):
    """
    Defines different styles for catapult messages.
    """

    plain = (None, None, [])
    green = ("green", None, [])
    yellow = ("yellow", None, [])
    blue = ("blue", None, [])
    red = ("red", None, [])
    red_inverse = ("white", "on_red", ["bold"])
    green_inverse = ("white", "on_green", ["bold"])

    def __init__(self, fg, bg, attrs):
        self.fg = fg
        self.bg = bg
        self.attrs = list(attrs)


@dataclasses.dataclass
class Formatted:
    text: Any
    style: TextStyle

    def __str__(self):
        return str(self.text)

    def __eq__(self, other):
        if isinstance(other, Formatted):
            other = other.text
        return self.text == other

    def __lt__(self, other):
        if isinstance(other, Formatted):
            other = other.text
        return self.text < other


def confirm(prompt, style=TextStyle.plain):
    _print(f"{prompt} [y/N] ", style)

    answer = input()

    return answer.lower() == "y"


def style_text(text: Any, style: TextStyle) -> str:
    text = str(text)
    return termcolor.colored(
        emoji.emojize(text, use_aliases=True), style.fg, style.bg, attrs=style.attrs
    )


def _print(text: str, style: TextStyle) -> None:
    end = ""
    if text and text[-1] == "\n":
        # Prevent background colours leaking to the next line
        text = text[:-1]
        end = "\n"
    print(style_text(text, style), end=end, file=sys.stderr)


success = partial(_print, style=TextStyle.green)
alert = partial(_print, style=TextStyle.green_inverse)
warning = partial(_print, style=TextStyle.yellow)
error = partial(_print, style=TextStyle.red_inverse)


def fatal(message: str, exit_code: int = 1):
    error(f"FATAL: {message}\n")
    sys.exit(exit_code)


@singledispatch
def to_human(data: Any):
    if dataclasses.is_dataclass(data):
        table = [
            [f.name, to_human(getattr(data, f.name))] for f in dataclasses.fields(data)
        ]
        return tabulate(table, [], tablefmt="simple")

    return str(data)


@to_human.register(list)
def _(data: list):
    text = ", ".join(to_human(v) for v in data)
    length = len(data)

    max_len = 100
    if len(text) > max_len:
        trunc = f"... ({length})"
        return text[: max_len - len(trunc)] + trunc

    return text


@to_human.register(dict)
def _(data: dict):
    table = [[h, data[h]] for h in sorted(data.keys())]
    return tabulate(table, [], tablefmt="simple")


@to_human.register(timedelta)
def _(data: timedelta):
    return format_timedelta(data)


@to_human.register(bool)
def _(data: bool):
    formatted = Formatted(str(data), TextStyle.green if data else TextStyle.red)
    return to_human(formatted)


@to_human.register(Formatted)
def _(data: Formatted):
    return style_text(data.text, data.style)


@to_human.register(enum.Enum)
def _(data: enum.Enum):
    return data.name


def to_human_tabular(rows: List[Mapping[str, Any]]):
    formatted_rows = [
        {key: "" if value is None else to_human(value) for key, value in row.items()}
        for row in rows
    ]

    return tabulate(formatted_rows, headers="keys", tablefmt="fancy_grid")


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
        fatal(f"invalid formatter: {fmt_name}")

    sys.stdout.write(fmt(data) + "\n")


def _aws_session(profile=config.AWS_PROFILE):
    if _SESSION:
        session = boto3.session.Session(
            profile_name=profile,
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


def get_region_name(profile=config.AWS_PROFILE):
    """
    Returns the region name of the given profile.

    Arguments:
        profile (str): profile's name.

    Returns:
        str: region name
    """
    return _aws_session(profile).region_name


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
            error("Cannot find git repository\n")
            return None

        path = path.parent


def get_author(repo: git.Repository, commit: git.Oid):

    if config.IS_CONCOURSE:
        return repo.get(commit).author.email

    # use git user email as release's author, or failing that, fall back to this commit's author

    emails = list(repo.config.get_multivar("user.email"))
    if emails:
        return emails[0]

    LOG.warning(
        "Unable to determine author from repo config. "
        "Falling back to author of most recent commit."
    )
    return repo.get(commit).author.email


class CommitNotFound(Exception):
    def __init__(self, commit_oid):
        self.commit_oid = commit_oid


def commit_contains(
    repo: git.Repository, commit: git.Oid, maybe_ancestor: git.Oid
) -> bool:
    # Does `commit` contain `maybe_ancestor`?

    if commit not in repo:
        raise CommitNotFound(commit)

    if maybe_ancestor not in repo:
        raise CommitNotFound(maybe_ancestor)

    if commit == maybe_ancestor:
        return True

    return repo.descendant_of(commit, maybe_ancestor)


class InvalidRange(Exception):
    pass


def git_log(
    repo: git.repository.Repository,
    *,
    start: Optional[git.Oid] = None,
    end: Optional[git.Oid] = None,
):

    if start is None:
        start = repo.head.target

    if start not in repo:
        fatal(
            f"Can't find commit {start.hex}. Are you in the right repo, or do you need to pull?"
        )

    for commit in repo.walk(start, git.GIT_SORT_TOPOLOGICAL):
        yield commit

        if commit.oid == end:
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
        return self._to_text(short=False)

    @property
    def short_text(self):
        return self._to_text(short=True)

    def _to_text(self, short):
        text = []

        for log in self.logs:
            commit_time = datetime.fromtimestamp(log.commit_time)
            message_lines = log.message.split("\n")

            if short:
                ref = str(log.short_id)
                date = commit_time.strftime("%Y-%m-%d")
                text.append(
                    f"{ref}  {date}  {log.author.name:20.20s}  {message_lines[0]}"
                )
            else:
                text.append(f"commit {log.hex}")
                text.append(f"Author: {log.author.name} <{log.author.email}>")
                text.append(f"Date:   {commit_time}")
                text.append("")
                text.extend("    " + line for line in message_lines)
                text.append("")

        return "\n".join(text)


def changelog(
    repo: git.repository.Repository,
    latest: git.Oid,
    prev: git.Oid,
    *,
    keep_only_files: Optional[List[str]] = None,
    keep_only_commits: Optional[List[str]] = None,
):
    rollback = False

    try:
        logs = list(git_log(repo=repo, start=latest, end=prev))[:-1]

    except InvalidRange:
        logs = reversed(list(git_log(repo=repo, start=prev, end=latest)))

        rollback = True

    if keep_only_files is not None:
        keep_only_files = set(keep_only_files)
        filtered_logs = []
        for commit in logs:
            diff = repo.diff(commit.parents[0], commit)
            all_files = {delta.new_file.path for delta in diff.deltas} | {
                delta.old_file.path for delta in diff.deltas
            }

            if keep_only_files & all_files:
                filtered_logs.append(commit)

        logs = filtered_logs

    if keep_only_commits:
        logs = [commit for commit in logs if commit.oid.hex in keep_only_commits]

    return Changelog(logs=logs, rollback=rollback)


def _refresh_session():
    global _SESSION

    if _SESSION:
        return

    if not config.AWS_MFA_DEVICE:
        return

    sts = sts_client()

    token_code = input(f"Enter MFA Token Code for device {config.AWS_MFA_DEVICE}: ")

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
        repo = git_repo()
        if not repo:
            return {}

        path = os.path.dirname(git_repo().path.rstrip("/"))
        path = os.path.join(path, ".catapult.toml")

        try:
            with open(path, "r") as fp:
                CONFIG = toml.load(fp)
        except FileNotFoundError:
            fatal(f"Can't find catapult config at {path}")

    return CONFIG


def revparse(repo: git.Repository, revision: str) -> git.Oid:
    try:
        return repo.revparse_single(revision).oid

    except KeyError as e:
        fatal(f"Commit not found in {repo.path}: {e}")

    except ValueError as e:
        fatal(f"Bad revision: {e}")

    except Exception as e:
        fatal(f"Unexpected error: {type(e).__name__}: {e}")
