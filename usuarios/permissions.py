# site-record/usuarios/permissions.py

from rest_framework import permissions

class CheckAPIPermission(permissions.BasePermission):
    """
    Verifica as permissões do usuário usando o sistema nativo do Django (Grupos e Permissions).
    
    Mantém a compatibilidade com a lógica antiga de 'resource_name' definida nas Views.
    Exemplo na View:
        class VendaViewSet(viewsets.ModelViewSet):
            permission_classes = [CheckAPIPermission]
            resource_name = 'venda'  # Nome do model (ex: 'venda', 'cliente')
    """
    def has_permission(self, request, view):
        # 1. Verifica se o usuário está logado
        if not request.user or not request.user.is_authenticated:
            return False

        # 2. Superusuário sempre tem acesso total
        if request.user.is_superuser:
            return True

        # 3. Identifica o recurso (Model) que a View está acessando
        resource_name = getattr(view, 'resource_name', None)
        if not resource_name:
            # Se a view não definir 'resource_name', bloqueia por segurança
            # (Ou permite se for apenas leitura, dependendo da sua política. Aqui bloqueamos.)
            print(f"ALERTA DE SEGURANÇA: 'resource_name' não definido em {view.__class__.__name__}")
            return False

        # 4. Mapeia o método HTTP para a ação do Django (view, add, change, delete)
        method_map = {
            'GET': 'view',
            'OPTIONS': 'view',
            'HEAD': 'view',
            'POST': 'add',
            'PUT': 'change',
            'PATCH': 'change',
            'DELETE': 'delete',
        }
        
        action = method_map.get(request.method)
        if not action:
            return False

        # 5. Constrói o codename da permissão (ex: 'crm_app.view_venda')
        # Nota: O 'app_label' padrão aqui é 'crm_app'. Se tiver recursos de outros apps, 
        # você pode precisar definir 'resource_app' na View também.
        app_label = getattr(view, 'resource_app', 'crm_app') 
        permission_codename = f'{app_label}.{action}_{resource_name}'

        # 6. Verifica se o usuário tem essa permissão (via Grupo ou direta)
        return request.user.has_perm(permission_codename)