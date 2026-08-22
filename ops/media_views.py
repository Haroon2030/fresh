"""Serve media files from local disk or Cloudflare R2."""
import mimetypes

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.views.decorators.http import require_GET


@require_GET
def media_proxy(request, path: str):
    """
    Serve /media/<path> from default storage (filesystem or R2).
    Private R2 buckets stay closed; this view streams the object.
    """
    path = (path or "").lstrip("/")
    if not path or ".." in path.split("/"):
        raise Http404("Not found")

    use_r2 = getattr(settings, "USE_R2", False)
    proxy = getattr(settings, "R2_PROXY_MEDIA", True)

    # Optional: redirect to short-lived signed URL instead of streaming
    if use_r2 and not proxy and getattr(settings, "R2_SIGNED_URLS", True):
        try:
            return HttpResponseRedirect(default_storage.url(path))
        except Exception as exc:
            raise Http404("Not found") from exc

    if not default_storage.exists(path):
        raise Http404("Not found")

    try:
        handle = default_storage.open(path, "rb")
    except Exception as exc:
        raise Http404("Not found") from exc

    content_type, _ = mimetypes.guess_type(path)
    response = FileResponse(handle, content_type=content_type or "application/octet-stream")
    response["Cache-Control"] = "private, max-age=3600"
    filename = path.rsplit("/", 1)[-1]
    if filename:
        response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
