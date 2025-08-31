from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Perfil

class CustomUserAdmin(UserAdmin):
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
    # A coluna 'descricao' não existe no modelo 'Usuario', foi removida daqui.
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')

@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    """
    Classe de Admin para o modelo Perfil.
    - list_display: Mostra 'nome' e 'descricao' na listagem.
    - fields: Permite editar 'nome' e 'descricao' no formulário.
    - search_fields: Adiciona uma barra de busca pelo campo 'nome'.
    """
    list_display = ('nome', 'descricao')
    fields = ('nome', 'descricao')
    search_fields = ('nome',)

# Registra o modelo Usuario com a classe de admin customizada
admin.site.register(Usuario, CustomUserAdmin)

# O modelo Perfil agora é registrado através do decorador @admin.register(Perfil)
# A linha abaixo não é mais necessária:
# admin.site.register(Perfil)