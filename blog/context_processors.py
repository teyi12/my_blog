from .seo import STATIC_PAGE_METADATA, build_default_seo, build_static_seo


def seo_metadata(request):
    match = request.resolver_match
    view_name = match.view_name if match else ""
    if view_name in STATIC_PAGE_METADATA:
        return {"seo": build_static_seo(request, view_name)}
    return {"seo": build_default_seo(request)}
