Catapult
========

A tool to create, deploy, and manage releases.

<p align="center"><img src="media/logo.png" height="256" alt="catapult logo"></p>

Installation
-------

> **Warning**
> _Requires `libssl-dev` and `libgit2` [*](#dependencies)_

Install using [pipx](https://pypa.github.io/pipx/) (recommended):

```
pipx install git+https://github.com/tessian/catapult
```


Getting started
-------

See [Useage](#useage) below for CLI useage.

Or run `catapult --help` or `catapult --help=<task>` to know more about
all the command's options.


1. Create an AWS account
2. Set up AWS credentials using any of the [recommended approches](https://docs.aws.amazon.com/sdk-for-java/v1/developer-guide/setup-credentials.html)


### Configuration

Set these environment variables to configure catapult:

* `CATAPULT_AWS_PROFILE` <sup>_[**Required**]_ </sup>: use this profile from your credential file. 
* `CATAPULT_TARGET_GIT_REPO` <sup>_[Optional]_ </sup>: path to the git repository (default: `./`).
  _If this is not set, catapult should be run inside the git repository_
* `CATAPULT_AWS_MFA_DEVICE` <sup>_[Optional]_ </sup>: ARN of the MFA device used to get the session credentials. You can find this on the "Security Credentials" tab of [your user account in IAM](https://console.aws.amazon.com/iam/home).

Additional environment variables used for integration with GitHub and Shortcut (formerly Clubhouse):

* `GITHUB_API_TOKEN`: A GitHub personal access token with `repo` scope. Generate one at https://github.com/settings/tokens
* `SHORTCUT_API_TOKEN`: A Shortcut API token. Generate one at https://app.shortcut.com/settings/account/api-tokens


So what exactly is Catapult?
-------

Catapult is a software release tool that leverages Amazon S3 to enable
the release process to have:

- Fine-grained permissioning
- An extensive audit trail
- Flexibility
- Two-factor Authentication
- High Speed & High Availability

The release process of an application, or project, is driven by a file
stored in a S3 bucket. The file contains information describing the release
and it's used by Concourse to create and deploy the build artifacts.

So, catapult is two things:

- a command line tool that manages state in an S3 bucket
- a [Concourse](https://concourse-ci.org/) Resource, that consumes said S3 bucket


### Command line

In the background this is doing a number of checks. It’s looking at S3,
git and our docker repository. Assuming they have the correct permissions,
this will update a file in S3, which our Catapult Concourse Resource is monitoring.


### Concourse resource

When the resource discovers a new version of the file, it will download it;
create a new version of the Concourse resource; display all the above
metadata; and – assuming it is set up to do so – trigger a new task.


### Metadata file

A release is identified by an integer **version**, this number increments
every release. **version_id** is the S3 version ID which is unique
a unique string assigned to a specific state of the object.

**commit** is the git reference to the code used for creating
the image or any final artifact. Every release is expected to produce
a final docker image which is identified by the image ID stored in
**image**.

The same structure is used to represent a deploy, but in this case
the version and the S3 version ID are used to identify a specific
deploy. This is needed to allow multiple deploy of the same version,
which is useful when rolling back a release to an older version.

The file contains other metadata regarding the release:

* **author**, who cut the release.
* **changelog**, all the changes introduced from the preceding release.
* **timestamp**, when the release was created.

Schema:

```
{
  "version": number (integer),
  "author": string (email address),
  "changelog": string,
  "commit": string (git sha),
  "image": string (docker image sha256),
  "timestamp": string (ISO8601),
  "version_id": string (S3 version)
}
```

Example:

```json
{
  "version": 2,
  "author": "foo@example.com",
  "changelog": "commit 42182bb85bebe8d7f...",
  "commit": "42182bb85bebe8d7f1ee515c13517be0dee8ada3",
  "image": "sha256:6ac40dec2b3af61e868954d641491d95a3fb74ad239d7584025b930d1f9997bd",
  "timestamp": "2018-07-03t17:14:18+00:00",
  "version_id": "qf.c4fqpt1wyaofxm_qeghylxsp_dogi"
}
```

### Why S3?

Storing and driving the release using a single S3 file allows us to:

* have a fine-grained control on the release and deploy permission using AWS IAM.
* keep a history of all the releases and deploys without relying on Concourse.
* store release's information in a single file using a _custom_ format.


Actions
-------

### Create release

`catapult release <name>` creates a new release of the application based
on the current git HEAD.

`catapult release <name> --commit=<git-sha>` allows to create a release
using the specified commit.

#### IAM Permissions

A user needs the below permissions to be able to release an application.

Resource: `arn:aws:s3:::<bucket>/<name>`

* `s3:PutObject`
* `s3:GetObject`
* `s3:ListBucketVersions`
* `s3:ListBucket`
* `s3:GetObjectVersion`

Resource: `arn:aws:s3:::<bucket>`

* `s3:ListAllMyBuckets`
* `s3:HeadBucket`


### Deploy release

`catapult deploy <name> <environment>` makes the latest release
available for deployment.

`catapult deploy <name> <environment> --version=<version>` this is useful
if the release to be deployed is not the latest (i.e. rollback).

#### IAM Permissions

A user needs the below permissions to be able to deploy an application.

Resource: `arn:aws:s3:::<bucket>/<name>`

* `s3:PutObject`
* `s3:GetObject`
* `s3:ListBucketVersions`
* `s3:ListBucket`
* `s3:GetObjectVersion`

Resource: `arn:aws:s3:::<bucket>`

* `s3:ListAllMyBuckets`
* `s3:HeadBucket`

Concourse Resource
------------------

Catapult commands are used to implement the resource type [release](./resource/README.md).

Docker
------

```bash
# build an image with catapult installed
docker build --target=catapult -t catapult -f Dockerfile .

# build an image for the concourse resource
docker build --target=release-resource -t release-resource -f Dockerfile .
```

Notes
-----

Most of the code relies on the client sending the correct information,
but more validation checks can be implemented in Concourse
to avoid the creation of invalid releases.

i.e.

A client can upload two releases with the same number twice, but
concourse will use only one of them and ignore the other one.


Dependencies
-----


### Linux

#### `apt`

```
sudo apt install libgit2 libssl-dev
```

#### `dnf`/`yum`

```
sudo dnf install libgit2 openssl-devel
```

### Mac

```
brew install libgit2 openssl
```



Contributing
-----

- Create a fork: https://github.com/tessian/catapult/fork
- Get local development setup ([poetry installation](https://python-poetry.org/docs/#installation))
```
git clone git@github.com:<username>/catapult.git
cd catapult
poetry install
poetry run pytest tests/
```
- Checkout a new branch and make changes
```
git checkout -b my-new-feature
vim some-changes.py
vim tests/tests-for-changes.py
poetry run pytest tests/
git add some-changes.py tests/tests-for-changes.py
git commit -m "Adding some-changes"
git push -u origin HEAD
```
- Create new pull request against `master`: https://github.com/Tessian/catapult/compare/master...<username>:my-new-feature
