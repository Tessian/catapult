Catapult
========

CLI Tool to create, deploy, and manage releases.

<p align="center"><img src="media/logo.png" height="256" alt="catapult logo"></p>

Install
-------

1. Create an AWS account
2. Set up AWS credentials using any of the [recommended approches](https://docs.aws.amazon.com/sdk-for-java/v1/developer-guide/setup-credentials.html)
3. Install [libgit2](https://libgit2.github.com/)

Linux:

```bash
wget https://github.com/libgit2/libgit2/archive/v0.27.0.tar.gz
tar xzf v0.27.0.tar.gz
cd libgit2-0.27.0/
cmake .
make
sudo make install

# Refresh cache for shared libraries
# https://github.com/libgit2/pygit2/issues/603
sudo ldconfig
```

MacOS
```bash
brew install libgit2
```

4. Install **catapult**:

```bash
cd ./tools/catapult
pip3 install -r requirements.txt
python3 setup.py develop
```

### Configuration

Set these environment variables to configure catapult:

* `CATAPULT_GIT_REPO`: path to the git repository (default: `./`).
  **!!! If this is not set, catapult should be run inside the git repository !!!**
* `CATAPULT_AWS_PROFILE`: use a specific profile from your credential file (default: `default`).
* `CATAPULT_AWS_MFA_DEVICE`: ARN of the MFA device used to get the session credentials.

Description
-----------

The release process of an application, or project, is driven by a file
stored in a S3 bucket. The file contains information describing the release
and it's used by Concourse to create and deploy the build artifacts.

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

### Documentation

Run `catapult --help` or `catapult --help=<task>` to know more about
all the command's options.

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
docker build --target=catapult -t release-resource -f Dockerfile .

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
