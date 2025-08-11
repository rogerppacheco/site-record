# usuarios/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Perfil

class CustomUserAdmin(UserAdmin):
    # Mantemos a exibição dos campos, mas removemos qualquer dependência
    # que possa causar erro na inicialização.
    fieldsets = UserAdmin.fieldsets + (
        ('Campos Personalizados', {
            'fields': ('perfil', 'cpf', 'supervisor', 'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta')
        }),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Campos Personalizados', {
            'fields': ('perfil', 'cpf', 'supervisor')
        }),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')

# Registra os modelos para que apareçam na interface de admin
admin.site.register(Usuario, CustomUserAdmin)
admin.site.register(Perfil)