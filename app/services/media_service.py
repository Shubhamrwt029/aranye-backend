import re
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config

from app.core.config import get_settings
from app.core.exceptions import AppException

settings = get_settings()


class MediaService:
    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )

    def object_key(self, kind: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename).stem).strip("-")[:80]
        return f"{kind}/{uuid4().hex}-{safe_stem or 'image'}{suffix}"

    def validate_size(self, size_bytes: int) -> None:
        if size_bytes > settings.media_max_upload_bytes:
            raise AppException(
                f"Image exceeds {settings.media_max_upload_bytes // 1_048_576} MB limit", 413
            )

    def validate_reel_size(self, size_bytes: int, content_type: str) -> None:
        maximum = (
            settings.media_max_video_upload_bytes
            if content_type.startswith("video/")
            else settings.media_max_upload_bytes
        )
        if size_bytes > maximum:
            media_label = "Video" if content_type.startswith("video/") else "Image"
            raise AppException(f"{media_label} exceeds {maximum // 1_048_576} MB limit", 413)

    def presign(self, object_key: str, content_type: str) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.media_presign_expire_seconds,
        )

    def public_url(self, object_key: str) -> str:
        base = settings.s3_public_base_url or (
            f"{settings.s3_endpoint_url.rstrip('/')}/{settings.s3_bucket}"
            if settings.s3_endpoint_url
            else f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com"
        )
        return f"{base.rstrip('/')}/{object_key}"

    def delete(self, object_key: str) -> None:
        self.client.delete_object(Bucket=settings.s3_bucket, Key=object_key)
