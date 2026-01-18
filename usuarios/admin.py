# site-record/usuarios/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Perfil, PermissaoPerfil

class PermissaoPerfilInline(admin.TabularInline):
    model = PermissaoPerfil
    extra = 1
    fields = ('recurso', 'pode_ver', 'pode_criar', 'pode_editar', 'pode_excluir')
    verbose_name = "Permissão"
    verbose_name_plural = "Permissões"
    can_delete = True
    show_change_link = False

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
            'description': 'OBS: O campo "Groups" acima também pode ser usado para definir perfis. O campo "Perfil" é opcional e legado.'
        }),
        ('Datas Importantes', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Informações Adicionais', {
            'fields': ('perfil', 'supervisor', 'canal', 'cpf'),
        }),
    )

    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_groups_display', 'perfil', 'canal')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups', 'perfil', 'canal')
    
    def get_groups_display(self, obj):
        """Mostra os grupos do usuário na listagem"""
        if obj.groups.exists():
            return ', '.join([g.name for g in obj.groups.all()])
        return '-'
    get_groups_display.short_description = 'Groups (Perfil)'

    def save_model(self, request, obj, form, change):
        """Override para sincronizar perfil com groups quando salvar pelo Django admin"""
        # Salva o modelo primeiro
        super().save_model(request, obj, form, change)
        
        # Sincroniza o campo perfil baseado nos groups
        # Se o usuário tem groups, usa o primeiro group para encontrar o perfil correspondente
        if obj.groups.exists():
            from usuarios.models import Perfil
            first_group = obj.groups.first()
            try:
                perfil = Perfil.objects.get(nome__iexact=first_group.name)
                if obj.perfil != perfil:
                    obj.perfil = perfil
                    obj.save(update_fields=['perfil'])
            except Perfil.DoesNotExist:
                # Se não encontrar perfil correspondente, limpa o campo
                if obj.perfil:
                    obj.perfil = None
                    obj.save(update_fields=['perfil'])
        else:
            # Se não tem groups, limpa o perfil
            if obj.perfil:
                obj.perfil = None
                obj.save(update_fields=['perfil'])
        
        # Sincroniza groups baseado no perfil (se perfil foi alterado diretamente)
        # Se o perfil foi definido manualmente e não corresponde aos groups, adiciona o group correspondente
        if obj.perfil:
            from django.contrib.auth.models import Group
            try:
                group = Group.objects.get(name__iexact=obj.perfil.nome)
                if not obj.groups.filter(id=group.id).exists():
                    # Se o group correspondente não está nos groups do usuário, adiciona
                    obj.groups.add(group)
            except Group.DoesNotExist:
                pass

# ======================================================
# --- CORREÇÃO APLICADA AQUI ---
# A linha admin.site.unregister(Usuario) foi REMOVIDA.
# Apenas registramos nosso admin customizado.
# ======================================================
admin.site.register(Usuario, CustomUserAdmin)