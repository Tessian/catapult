import os
import sys

_HOME_PATH = os.path.expanduser("~")

# aws config
AWS_MFA_DEVICE = os.environ.get("CATAPULT_AWS_MFA_DEVICE")

AWS_PROFILE = os.environ.get("CATAPULT_AWS_PROFILE")
if not AWS_PROFILE:
    print("The environment variable CATAPULT_AWS_PROFILE is required.")
    sys.exit(1)

# git config
GIT_REPO = os.environ.get("CATAPULT_TARGET_GIT_REPO") or os.environ.get(
    "CATAPULT_GIT_REPO", "./"
)

# catapult config
CATAPULT_SESSION = os.environ.get(
    "CATAPULT_SESSION", os.path.join(_HOME_PATH, ".catapult")
)


IS_CONCOURSE = bool(os.environ.get("IS_CONCOURSE"))
