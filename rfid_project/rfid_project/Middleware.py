from django.shortcuts import redirect


class RedirectMiddleware:

	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		response = self.get_response(request)
		# allow the device/process endpoint to be accessed without authentication
		if not request.user.is_authenticated and "/login/" not in request.path and "/process/" not in request.path:
			return redirect('login')
		return response
