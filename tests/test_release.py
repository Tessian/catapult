import json
from datetime import datetime
from unittest import mock

import boto3
import pytz
from freezegun import freeze_time
from invoke import MockContext, Result
from moto import mock_s3
from testfixtures import compare

from catapult import release

# Mock default bucket name to stop the tests from using a real
# bucket by mistake
_PATCHER = mock.patch("catapult.utils.CONFIG", {"release": {"s3_bucket": "test"}})


def setUpModule():
    _PATCHER.start()


def tearDownModule():
    _PATCHER.stop()


@mock_s3
@freeze_time("2018-01-01T12:00:00")
def test_get_release_from_bucket():
    """
    Gets the release from an object stored in a S3 bucket.
    """
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    resp = client.put_object(
        Bucket="test",
        Key="test-app",
        Body=json.dumps(
            {
                "version": 2,
                "commit": "0123456789abcdef",
                "changelog": "some changes",
                "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                "author": "author@example.com",
            }
        ),
    )

    expected = release.Release(
        version=2,
        commit="0123456789abcdef",
        changelog="some changes",
        version_id=resp["VersionId"],
        image="sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
        timestamp=datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc),
        author="author@example.com",
    )

    r = release._get_release(client, "test", "test-app", None)

    compare(expected, r)


@mock_s3
def test_get_latest_release():
    """
    Gets the latest release when the object's Version ID is not specified.
    """
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    with freeze_time("2018-01-01T12:00:00"):
        client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 1,
                    "commit": "0123456789abcdef",
                    "changelog": "some changes",
                    "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                    "author": "author@example.com",
                }
            ),
        )

    with freeze_time("2018-02-02T00:00:00"):
        new = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 2,
                    "commit": "abcdef0123456789",
                    "changelog": "some other changes to fix version 1",
                    "image": "sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
                    "author": "author@example.com",
                }
            ),
        )

    expected = release.Release(
        version=2,
        commit="abcdef0123456789",
        changelog="some other changes to fix version 1",
        version_id=new["VersionId"],
        image="sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
        timestamp=datetime(2018, 2, 2, 0, 0, 0, tzinfo=pytz.utc),
        author="author@example.com",
    )

    r = release._get_release(client, "test", "test-app", None)

    compare(expected, r)


@mock_s3
def test_get_older_release():
    """
    Gets an old release using its object Version ID.
    """
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    with freeze_time("2018-01-01T12:00:00"):
        old = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 1,
                    "commit": "0123456789abcdef",
                    "changelog": "some changes",
                    "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                    "author": "author@example.com",
                }
            ),
        )

    with freeze_time("2018-02-02T00:00:00"):
        client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 2,
                    "commit": "abcdef0123456789",
                    "changelog": "some other changes to fix version 1",
                    "image": "sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
                    "author": "author@example.com",
                }
            ),
        )

    expected = release.Release(
        version=1,
        commit="0123456789abcdef",
        changelog="some changes",
        version_id=old["VersionId"],
        image="sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
        timestamp=datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc),
        author="author@example.com",
    )

    r = release._get_release(client, "test", "test-app", old["VersionId"])

    compare(expected, r)


@mock_s3
def test_get_releases_no_releases_yet():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    rs = release.get_releases(client, "test-app", bucket="test")

    compare([], list(rs))


@mock_s3
def test_get_all_releases():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    with freeze_time("2018-01-01T12:00:00"):
        old = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 1,
                    "commit": "0123456789abcdef",
                    "changelog": "some changes",
                    "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                    "author": "author@example.com",
                }
            ),
        )

    with freeze_time("2018-02-02T00:00:00"):
        new = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 2,
                    "commit": "abcdef0123456789",
                    "changelog": "some other changes to fix version 1",
                    "image": "sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
                    "author": "author@example.com",
                }
            ),
        )

    rs = release.get_releases(client, "test-app", bucket="test")

    expected = [
        release.Release(
            version=2,
            commit="abcdef0123456789",
            changelog="some other changes to fix version 1",
            version_id=new["VersionId"],
            image="sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
            timestamp=datetime(2018, 2, 2, 0, 0, 0, tzinfo=pytz.utc),
            author="author@example.com",
        ),
        release.Release(
            version=1,
            commit="0123456789abcdef",
            changelog="some changes",
            version_id=old["VersionId"],
            image="sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
            timestamp=datetime(2018, 1, 1, 12, 0, 0, tzinfo=pytz.utc),
            author="author@example.com",
        ),
    ]

    compare(expected, list(rs))


@mock_s3
def test_get_releases_skips_non_versioned_objects():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")

    with freeze_time("2018-01-01T12:00:00"):
        client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 1,
                    "commit": "0123456789abcdef",
                    "changelog": "some changes",
                    "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                    "author": "author@example.com",
                }
            ),
        )

    bucket = s3.BucketVersioning("test")
    bucket.enable()

    with freeze_time("2018-02-02T00:00:00"):
        new = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 2,
                    "commit": "abcdef0123456789",
                    "changelog": "some other changes to fix version 1",
                    "image": "sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
                    "author": "author@example.com",
                }
            ),
        )

    rs = release.get_releases(client, "test-app", bucket="test")

    expected = [
        release.Release(
            version=2,
            commit="abcdef0123456789",
            changelog="some other changes to fix version 1",
            version_id=new["VersionId"],
            image="sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
            timestamp=datetime(2018, 2, 2, 0, 0, 0, tzinfo=pytz.utc),
            author="author@example.com",
        )
    ]

    compare(expected, list(rs))


@mock_s3
def test_get_releases_skips_objects_with_invalid_data():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    # missing fields
    client.put_object(
        Bucket="test",
        Key="test-app",
        Body=json.dumps(
            {
                "changelog": "some changes",
                "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                "author": "author@example.com",
            }
        ),
    )

    # invalid JSON
    client.put_object(Bucket="test", Key="test-app", Body='{ "this": "is" invalid')

    with freeze_time("2018-02-02T00:00:00"):
        new = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 2,
                    "commit": "abcdef0123456789",
                    "changelog": "some other changes to fix version 1",
                    "image": "sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
                    "author": "author@example.com",
                }
            ),
        )

    rs = release.get_releases(client, "test-app", bucket="test")

    expected = [
        release.Release(
            version=2,
            commit="abcdef0123456789",
            changelog="some other changes to fix version 1",
            version_id=new["VersionId"],
            image="sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
            timestamp=datetime(2018, 2, 2, 0, 0, 0, tzinfo=pytz.utc),
            author="author@example.com",
        )
    ]

    compare(expected, list(rs))


@mock_s3
def test_get_releases_since():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    with freeze_time("2018-01-01T12:00:00"):
        client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 1,
                    "commit": "0123456789abcdef",
                    "changelog": "some changes",
                    "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                    "author": "author@example.com",
                }
            ),
        )

    with freeze_time("2018-02-02T00:00:00"):
        second = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 2,
                    "commit": "abcdef0123456789",
                    "changelog": "some other changes to fix version 1",
                    "image": "sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
                    "author": "author@example.com",
                }
            ),
        )

    with freeze_time("2018-03-03T00:00:00"):
        third = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 3,
                    "commit": "zxcvbnm12345",
                    "changelog": "new awesome feature",
                    "image": "sha256:b0190de683bc5d190c4c09473e0d2a5696850f22244cd8e9fc925117580b6361",
                    "author": "author@example.com",
                }
            ),
        )

    rs = release.get_releases(client, "test-app", since=2, bucket="test")

    expected = [
        release.Release(
            version=3,
            commit="zxcvbnm12345",
            changelog="new awesome feature",
            version_id=third["VersionId"],
            image="sha256:b0190de683bc5d190c4c09473e0d2a5696850f22244cd8e9fc925117580b6361",
            timestamp=datetime(2018, 3, 3, 0, 0, 0, tzinfo=pytz.utc),
            author="author@example.com",
        ),
        release.Release(
            version=2,
            commit="abcdef0123456789",
            changelog="some other changes to fix version 1",
            version_id=second["VersionId"],
            image="sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
            timestamp=datetime(2018, 2, 2, 0, 0, 0, tzinfo=pytz.utc),
            author="author@example.com",
        ),
    ]

    compare(expected, list(rs))


@mock_s3
def test_get_release():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    with freeze_time("2018-01-01T12:00:00"):
        client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 1,
                    "commit": "0123456789abcdef",
                    "changelog": "some changes",
                    "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                    "author": "author@example.com",
                }
            ),
        )

    with freeze_time("2018-02-02T00:00:00"):
        second = client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 2,
                    "commit": "abcdef0123456789",
                    "changelog": "some other changes to fix version 1",
                    "image": "sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
                    "author": "author@example.com",
                }
            ),
        )

    r = release.get_release(client, "test-app", 2, bucket="test")

    expected = release.Release(
        version=2,
        commit="abcdef0123456789",
        changelog="some other changes to fix version 1",
        version_id=second["VersionId"],
        image="sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
        timestamp=datetime(2018, 2, 2, 0, 0, 0, tzinfo=pytz.utc),
        author="author@example.com",
    )

    compare(expected, r)


@mock_s3
def test_get_release_not_found():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    with freeze_time("2018-01-01T12:00:00"):
        client.put_object(
            Bucket="test",
            Key="test-app",
            Body=json.dumps(
                {
                    "version": 1,
                    "commit": "0123456789abcdef",
                    "changelog": "some changes",
                    "image": "sha256:eb1494dee949e52c20084672700c9961d7fc99d1be1c07b5492bc61c3b22a460",
                    "author": "author@example.com",
                }
            ),
        )

    r = release.get_release(client, "test-app", 2, bucket="test")

    compare(None, r)


@mock_s3
@freeze_time("2018-01-01T12:00:00")
def test_create_new_release():
    s3 = boto3.resource("s3")
    client = boto3.client("s3")

    s3.create_bucket(Bucket="test")
    bucket = s3.BucketVersioning("test")
    bucket.enable()

    new = release.Release(
        version=1,
        commit="abcdef0123456789",
        changelog="some changes",
        version_id=None,
        image="sha256:000dd6d0c34dd4bb2ec51316ec41f723dd546ef79b30e551ec8390d032707351",
        timestamp=None,
        author="author@example.com",
    )

    pushed = release.put_release(client, "test", "test-app", new)
    fetched = release.get_release(client, "test-app", 1, bucket="test")

    compare(pushed, fetched)
