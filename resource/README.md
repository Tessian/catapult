# Release Resource

Tracks and creates a realease.

## Source Configuration

* `name`: *Required.* The name of the application or project to release.

* `bucket`: *Required.* Name of the S3 bucket used to store the release.

* `aws_access_key_id`: *Optional.* AWS access key to use for downloading
  the release from S3.

* `aws_secret_access_key`: *Optional.* AWS secret key to use for downloading
  the release from S3.

* `aws_session_token`: *Optional.* AWS session token (assumed role) to use
  for downloading the release from S3.

* `is_deploy`: *Optional.* When this parameter is set to `true`, the
  release will be treated as a deploy request.

* `environment`: *Optional, default="staging".* Name of the environment where the application
  will be deployed. This is used only when `is_deploy` is set.

## Behavior

### `check`: Check for new releases.

The current version of the release is fetched from S3 for the given project.

A release is identified by its version, except for deploys that are
identified by version and S3 version ID to allow concourse to perfor
multiple deploys of the same version (i.e. rollbacks).

### `in`: Fetch the release from S3.

Pulls down the release by the requested version.

The following files will be placed in the destination:

* `release.json`: output of `catapult release.current` in JSON format.
  It contains all the information regarding the release.
* `version`: the release's version.
* `commit`: hash ref of the released git commit.
* `image-id`: ID of the released docker image.
* `changelog`: text describing the changes included in the release.
* `environment`: name of the environment.
* `git-tag`: Tag in the format `<app-name>-v<version>`, eg `my_app-v42`. For use by
  `git-resource`'s `out` step. (See the
  [git-resource docs](https://github.com/concourse/git-resource#parameters-1) for more
  information.)

#### Parameters

_None_.

### `out`: Creates a new release.

Create and upload a new release.

#### Parameters

* `repository`: *Required.* Path to the git repository where the project
  to release is tracked.

* `version`: *Optional.* Path to the file containing the version for
   the new release. If the version is not set, it will use the next version.


## Development

### Prerequisites

* golang is *required* - version 1.9.x is tested; earlier versions may also
  work.
* docker is *required* - version 17.06.x is tested; earlier versions may also
  work.

### Running the tests

The tests have been embedded with the `Dockerfile`; ensuring that the testing
environment is consistent across any `docker` enabled platform. When the docker
image builds, the test are run inside the docker container, on failure they
will stop the build.

Build the image and run the tests with the following command:

```sh
docker build -t docker-image-resource .
```

To use the newly built image, push it to a docker registry that's accessible to
Concourse and configure your pipeline to use it:

```yaml
resource_types:
- name: docker-image-resource
  type: docker-image
  privileged: true
  source:
    repository: example.com:5000/docker-image-resource
    tag: latest

resources:
- name: some-image
  type: docker-image-resource
  ...
```

### Contributing

Please make all pull requests to the `master` branch and ensure tests pass
locally.
