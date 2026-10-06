"""
Phase 4: Cloud Storage Service
================================
Wraps AWS S3 operations behind a clean interface.

Why abstract S3 behind a service class?
- Easy to swap (S3 → GCS → local disk) without touching the rest of the code
- Easier to mock in tests
- Single place to handle errors / retries

S3 Key concepts
---------------
• Bucket   : A named container for files (like a top-level folder)
• Key      : The path/filename inside the bucket (e.g. "renders/abc123_original.jpg")
• Object   : A file stored at Bucket/Key
• Presigned URL : A temporary URL that grants read access without authentication
• ACL      : Access control list; "public-read" makes objects publicly accessible

AWS Credentials setup (production)
-----------------------------------
    export AWS_ACCESS_KEY_ID=your_key
    export AWS_SECRET_ACCESS_KEY=your_secret
    export AWS_DEFAULT_REGION=us-east-1
    export S3_BUCKET_NAME=my-renderer-bucket

Local development
-----------------
Set USE_LOCAL_STORAGE=true to save to disk instead of S3.
This lets you develop Phase 4 logic without an AWS account.
"""

import os
import uuid
import mimetypes
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timezone


# ─────────────────────────────────────────────
# LOCAL STORAGE FALLBACK (for dev/testing)
# ─────────────────────────────────────────────
LOCAL_STORAGE_DIR = Path(os.getenv("LOCAL_STORAGE_DIR", "/tmp/stylized_storage"))
LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

USE_LOCAL = os.getenv("USE_LOCAL_STORAGE", "true").lower() == "true"


class StorageService:
    """
    Unified interface for storing and retrieving render images.
    Supports AWS S3 (production) and local disk (development).
    """

    def __init__(self):
        self.use_local = USE_LOCAL
        self.bucket    = os.getenv("S3_BUCKET_NAME", "stylized-renderer-dev")
        self.region    = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

        if not self.use_local:
            import boto3
            self.s3 = boto3.client(
                "s3",
                region_name=self.region,
                # In production, credentials come from env vars or IAM role.
                # boto3 reads AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY automatically.
            )
        else:
            self.s3 = None

    # ─────────────────────────────────────────
    # UPLOAD
    # ─────────────────────────────────────────
    def upload_image(
        self,
        image_bytes: bytes,
        folder: str = "renders",
        filename_suffix: str = "",
        content_type: str = "image/jpeg",
    ) -> Tuple[str, str]:
        """
        Upload image bytes to storage.

        Returns
        -------
        (key, url) where:
            key = storage path (S3 key or local relative path)
            url = publicly accessible URL to the image
        """
        key = f"{folder}/{uuid.uuid4().hex}{filename_suffix}.jpg"

        if self.use_local:
            return self._upload_local(image_bytes, key)
        else:
            return self._upload_s3(image_bytes, key, content_type)

    def _upload_local(self, image_bytes: bytes, key: str) -> Tuple[str, str]:
        """Save to local disk and return a file:// URL."""
        path = LOCAL_STORAGE_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image_bytes)
        url = f"file://{path}"
        return key, url

    def _upload_s3(self, image_bytes: bytes, key: str,
                   content_type: str) -> Tuple[str, str]:
        """Upload to S3 and return a public HTTPS URL."""
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=image_bytes,
            ContentType=content_type,
            # ACL="public-read",  # uncomment if your bucket allows public access
        )
        url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
        return key, url

    # ─────────────────────────────────────────
    # PRESIGNED URL (S3 only, for private buckets)
    # ─────────────────────────────────────────
    def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Generate a temporary signed URL for a private S3 object.
        Useful when you don't want files to be permanently public.

        expires_in : seconds until URL expires (default 1 hour)
        """
        if self.use_local:
            path = LOCAL_STORAGE_DIR / key
            return f"file://{path}"

        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    # ─────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────
    def delete(self, key: str) -> bool:
        """Delete a file from storage. Returns True on success."""
        try:
            if self.use_local:
                path = LOCAL_STORAGE_DIR / key
                if path.exists():
                    path.unlink()
                return True
            else:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
                return True
        except Exception:
            return False

    def info(self) -> dict:
        return {
            "backend":   "local_disk" if self.use_local else "aws_s3",
            "bucket":    self.bucket,
            "local_dir": str(LOCAL_STORAGE_DIR) if self.use_local else None,
        }


# Singleton instance
storage = StorageService()
