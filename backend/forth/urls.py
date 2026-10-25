from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.http import HttpResponseNotFound
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from oauth2_provider.urls import base_urlpatterns, metadata_urlpatterns, management_urlpatterns
from core.mcp_views import MCPView, OAuthLoginView
from core.usage_views import UsageSummaryView
from core.access_views import RecoveryView, ResetPasswordView, DeleteAccountView, PublicAccessView, AccountTokenRefreshView
from core.start_views import SearchSetupView, StartDiscoveryView
from core.account_views import AccountSettingsView, AccountModelsView

from core.views import (
    AgentRunViewSet,
    ApplicationEventViewSet,
    ApplicationViewSet,
    ApprovalRequestViewSet,
    ArtifactViewSet,
    CandidatePreferenceViewSet,
    CandidateOnboardingView,
    CandidateProfileView,
    ConversationThreadViewSet,
    CoverLetterViewSet,
    DashboardView,
    FrontendAppView,
    JobMatchViewSet,
    JobPostingViewSet,
    JobSourceViewSet,
    ProfileDocumentViewSet,
    ProfileFactViewSet,
    ResumeViewSet,
    RegistrationView,
    SourceRunViewSet,
    StrategyView,
    TodayView,
)

router = DefaultRouter()
router.register('profile/documents', ProfileDocumentViewSet, basename='profile-document')
router.register('profile/facts', ProfileFactViewSet, basename='profile-fact')
router.register('profile/preferences', CandidatePreferenceViewSet, basename='candidate-preference')
router.register('sources', JobSourceViewSet, basename='job-source')
router.register('source-runs', SourceRunViewSet, basename='source-run')
router.register('jobs', JobPostingViewSet, basename='job')
router.register('matches', JobMatchViewSet, basename='job-match')
router.register('resumes', ResumeViewSet, basename='resume')
router.register('cover-letters', CoverLetterViewSet, basename='cover-letter')
router.register('applications', ApplicationViewSet, basename='application')
router.register('application-events', ApplicationEventViewSet, basename='application-event')
router.register('artifacts', ArtifactViewSet, basename='artifact')
router.register('conversations', ConversationThreadViewSet, basename='conversation-thread')
router.register('agent-runs', AgentRunViewSet, basename='agent-run')
router.register('approvals', ApprovalRequestViewSet, basename='approval-request')

urlpatterns = metadata_urlpatterns + [
    path('media/<path:path>', lambda request, path: HttpResponseNotFound()),
    path('mcp/', MCPView.as_view(), name='mcp'),
    path('oauth/logout/', LogoutView.as_view(next_page='/'), name='oauth-logout'),
    path('oauth/login/', OAuthLoginView.as_view(), name='oauth-login'),
    path('oauth/', include((base_urlpatterns + [p for p in management_urlpatterns if p.name.startswith('authorized-token')], 'oauth2_provider'), namespace='oauth2_provider')),
    path('admin/', admin.site.urls),
    path('api/access/', PublicAccessView.as_view(), name='public-access'),
    path('api/auth/recovery/', RecoveryView.as_view(), name='account-recovery'),
    path('api/auth/reset/', ResetPasswordView.as_view(), name='account-reset'),
    path('api/account/delete/', DeleteAccountView.as_view(), name='account-delete'),
    path('api/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/signup/', RegistrationView.as_view(), name='signup'),
    path('api/auth/refresh/', AccountTokenRefreshView.as_view(), name='token_refresh'),
    path('api/account/settings/', AccountSettingsView.as_view(), name='account-settings'),
    path('api/account/models/', AccountModelsView.as_view(), name='account-models'),
    path('api/usage/', UsageSummaryView.as_view(), name='usage-summary'),
    path('api/dashboard/', DashboardView.as_view(), name='dashboard'),
    path('api/start/', SearchSetupView.as_view(), name='search-setup'),
    path('api/start/discover/', StartDiscoveryView.as_view(), name='start-discovery'),
    path('api/today/', TodayView.as_view(), name='today'),
    path('api/profile/', CandidateProfileView.as_view(), name='candidate-profile'),
    path('api/profile/onboarding/', CandidateOnboardingView.as_view(), name='candidate-onboarding'),
    path('api/strategy/', StrategyView.as_view(), name='strategy'),
    path('api/', include(router.urls)),
    path('', FrontendAppView.as_view(), name='app'),
    path('<path:path>', FrontendAppView.as_view(), name='app-path'),
]
