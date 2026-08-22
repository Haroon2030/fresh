"""Cloudflare R2 storage (S3-compatible) for media uploads."""
from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class R2MediaStorage(S3Boto3Storage):
    """Private R2 bucket — keys under R2_LOCATION (default media/fresh/)."""

    default_acl = None
    file_overwrite = False
    address_style = "path"
    signature_version = "s3v4"

    def __init__(self, **kwargs):
        kwargs.setdefault("bucket_name", settings.R2_BUCKET_NAME)
        kwargs.setdefault("access_key", settings.R2_ACCESS_KEY_ID)
        kwargs.setdefault("secret_key", settings.R2_SECRET_ACCESS_KEY)
        kwargs.setdefault("endpoint_url", settings.R2_ENDPOINT_URL)
        kwargs.setdefault("region_name", settings.R2_REGION or "auto")
        kwargs.setdefault("default_acl", None)
        kwargs.setdefault("querystring_auth", bool(settings.R2_SIGNED_URLS))
        kwargs.setdefault("querystring_expire", int(settings.R2_SIGNED_URL_EXPIRE))
        kwargs.setdefault("file_overwrite", False)
        kwargs.setdefault("location", (settings.R2_LOCATION or "").strip("/"))
        kwargs.setdefault("object_parameters", {"CacheControl": "max-age=86400"})
        kwargs.setdefault("addressing_style", "path")
        kwargs.setdefault("signature_version", "s3v4")
        super().__init__(**kwargs)

    def url(self, name, parameters=None, expire=None, http_method=None):
        # Keep /media/... URLs; Django serves via media_proxy from private R2
        if getattr(settings, "R2_PROXY_MEDIA", True):
            clean = str(name or "").replace("\\", "/").lstrip("/")
            base = (settings.MEDIA_URL or "/media/").rstrip("/")
            return f"{base}/{clean}"

        public = (getattr(settings, "R2_PUBLIC_DOMAIN", "") or "").rstrip("/")
        if public and not settings.R2_SIGNED_URLS:
            if hasattr(self, "_normalize_name"):
                clean = self._normalize_name(str(name or "")).lstrip("/")
            else:
                loc = (self.location or "").strip("/")
                clean = f"{loc}/{str(name).lstrip('/')}" if loc else str(name).lstrip("/")
            return f"{public}/{clean}"

        return super().url(
            name, parameters=parameters, expire=expire, http_method=http_method
        )
