class PermissionsPolicyMiddleware:
    """Disable browser capabilities that the application never uses."""

    policy = "camera=(), microphone=(), geolocation=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", self.policy)
        return response
