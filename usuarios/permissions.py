from rest_framework import permissions

class CheckAPIPermission(permissions.BasePermission):
    """
    Verifica as permissões do usuário dinamicamente com base no
    modelo PermissaoPerfil no banco de dados.

    Para usar, você deve definir um atributo 'resource_name' na sua ViewSet.
    Exemplo:
        class VendaViewSet(viewsets.ModelViewSet):
            permission_classes = [CheckAPIPermission]
            resource_name = 'vendas' # O nome do recurso como está no BD
            ...
    """
    def has_permission(self, request, view):
        # O usuário precisa estar autenticado para continuar
        if not request.user or not request.user.is_authenticated:
            return False

        # Superusuário e o perfil 'Diretoria' sempre terão acesso total
        if request.user.is_superuser or (hasattr(request.user, 'perfil') and request.user.perfil and request.user.perfil.nome == 'Diretoria'):
            return True

        # Pega o nome do recurso definido na ViewSet (ex: 'vendas', 'presenca')
        resource_name = getattr(view, 'resource_name', None)
        if not resource_name:
            # Por segurança, se o programador esqueceu de definir o nome do recurso na view, o acesso é negado.
            print(f"ALERTA DE SEGURANÇA: 'resource_name' não foi definido em {view.__class__.__name__}")
            return False

        # Mapeia o método HTTP (GET, POST, etc.) para o campo de permissão no seu modelo
        method_map = {
            'GET': 'pode_ver',
            'OPTIONS': 'pode_ver', # Geralmente usado para pre-flight requests
            'HEAD': 'pode_ver',
            'POST': 'pode_criar',
            'PUT': 'pode_editar',
            'PATCH': 'pode_editar',
            'DELETE': 'pode_excluir',
        }
        required_permission_field = method_map.get(request.method)

        if not required_permission_field:
            return False # Nega acesso se o método HTTP não for reconhecido

        # Verifica se existe uma permissão no banco de dados para o perfil do usuário
        # que corresponda ao recurso e à ação necessária.
        if not hasattr(request.user, 'perfil') or not request.user.perfil:
            return False # Nega acesso se o usuário não tiver perfil
        
        # Esta é a consulta principal:
        has_perm = request.user.perfil.permissoes.filter(
            recurso=resource_name,
            **{required_permission_field: True} # Isso se transforma em, por exemplo, pode_ver=True
        ).exists()

        return has_perm