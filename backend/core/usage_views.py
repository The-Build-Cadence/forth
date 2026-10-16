from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .usage import usage_summary


class UsageSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(usage_summary(request.user))
