class PrivateResponseMiddleware:
    """Prevent shared caches and browser history caches retaining private responses."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(('/api/', '/mcp/', '/oauth/')):
            response['Cache-Control'] = 'no-store'
        return response
