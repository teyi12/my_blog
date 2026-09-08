from django.http import HttpResponse
from django.urls import reverse

from .seo import absolute_url


def robots_txt(request):
    sitemap_url = absolute_url(request, reverse("sitemap"), force_https=True)
    content = "\n".join(
        (
            "User-agent: *",
            "Allow: /",
            "Disallow: /admin/",
            "Disallow: /payments/",
            "Disallow: /i18n/",
            f"Sitemap: {sitemap_url}",
            "",
        )
    )
    return HttpResponse(content, content_type="text/plain; charset=utf-8")
