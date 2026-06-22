"""Pydantic model locating an object in an AWS S3 bucket."""

from pydantic import BaseModel


class S3Locator(BaseModel):
    """Bucket/key/region triple identifying an object in S3.

    Attributes:
        bucket (str): S3 bucket name.
        key (str): Object key within the bucket.
        region (str): AWS region of the bucket.
    """

    bucket: str
    key: str
    region: str

    @property
    def url(self) -> str:
        """Return the ``s3://bucket/key`` URL for the object."""
        return f"s3://{self.bucket}/{self.key}"
