# gestao_equipes/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView
from usuarios.views import MyTokenObtainPairView

# Unificando os endpoints da API sob um único prefixo para maior clareza
api_urlpatterns = [
    path('', include('presenca.urls')),
    path('', include('usuarios.urls')),
    path('relatorios/', include('relatorios.urls')),
    path('crm-cadastros/', include('crm_app.urls')),
]

urlpatterns = [
    path('', include('core.urls')),
    path('admin/', admin.site.urls),
    
    # URL principal da API que inclui todos os outros endpoints
    path('api/', include(api_urlpatterns)),

    # Rotas de Autenticação
    path('api/auth/login', MyTokenObtainPairView.as_view(), name='token_obtain_pair_legacy'),
    path('api/token/', MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]