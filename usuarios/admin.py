# site-record/usuarios/admin.py

from django.contrib import admin
# A forma correta de importar o User, especialmente um customizado
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from .models import Perfil, PermissaoPerfil

# Pega o modelo de usuário que está ativo no projeto
User = get_user_model()

# Usa o decorador @admin.register, que é mais limpo
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('perfil', 'supervisor')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('perfil', 'supervisor')}),
    )
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff', 'perfil']
    list_filter = ['perfil', 'is_staff', 'is_superuser', 'groups']

@admin.register(PermissaoPerfil)
class PermissaoPerfilAdmin(admin.ModelAdmin):
    list_display = ('perfil', 'recurso', 'pode_ver', 'pode_criar', 'pode_editar', 'pode_excluir')
    list_filter = ('perfil', 'recurso')
    search_fields = ('perfil__nome', 'recurso')
    ordering = ('perfil__nome', 'recurso')

# Registra o Perfil que não tem uma classe de admin customizada
admin.site.register(Perfil)