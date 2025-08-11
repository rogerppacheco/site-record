# gestao_equipes/urls.py
from django.contrib import admin
from django.urls import path, include

from rest_framework_simplejwt.views import TokenRefreshView
from usuarios.views import MyTokenObtainPairView

urlpatterns = [
    path('', include('core.urls')),
    path('admin/', admin.site.urls),
    
    path('api/', include('presenca.urls')),
    path('api/', include('usuarios.urls')),
    path('api/relatorios/', include('relatorios.urls')),
    path('api/crm-cadastros/', include('crm_app.urls')), # <-- NOME CORRIGIDO

    path('api/token/', MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]