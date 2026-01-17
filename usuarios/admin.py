# site-record/usuarios/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Perfil, PermissaoPerfil

class PermissaoPerfilInline(admin.TabularInline):
    model = PermissaoPerfil
    extra = 1

@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cod_perfil')
    list_filter = ('nome',)
    search_fields = ('nome', 'cod_perfil')
    inlines = [PermissaoPerfilInline]

class CustomUserAdmin(UserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informações Pessoais', {'fields': ('first_name', 'last_name', 'email', 'cpf')}),
        ('Função e Estrutura', {'fields': ('perfil', 'supervisor', 'canal')}),
        ('Financeiro', {'fields': (
            'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta'
        )}),
        ('Comissionamento', {'fields': (
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 'adiantamento_cnpj', 'desconto_inss_fixo'
        )}),
        ('Permissões', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Datas Importantes', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Informações Adicionais', {
            'fields': ('perfil', 'supervisor', 'canal', 'cpf'),
        }),
    )

    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'perfil', 'canal')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups', 'perfil', 'canal')

# ======================================================
# --- CORREÇÃO APLICADA AQUI ---
# A linha admin.site.unregister(Usuario) foi REMOVIDA.
# Apenas registramos nosso admin customizado.
# ======================================================
admin.site.register(Usuario, CustomUserAdmin)