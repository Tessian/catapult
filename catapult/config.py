import os

_HOME_PATH = os.path.expanduser("~")

# aws config
AWS_PROFILE = os.environ.get("CATAPULT_AWS_PROFILE", "default")
AWS_MFA_DEVICE = os.environ.get("CATAPULT_AWS_MFA_DEVICE")

# git config
GIT_REPO = os.environ.get("CATAPULT_GIT_REPO", "./")

# catapult config
CATAPULT_SESSION = os.environ.get(
    "CATAPULT_SESSION", os.path.join(_HOME_PATH, ".catapult")
)
