"""
APIs para Record Apoia - Repositório de Arquivos
"""
import os
import re
from django.http import FileResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q
from .models import RecordApoia

# Validações de segurança
ALLOWED_EXTENSIONS = {
    'PDF': ['.pdf'],
    'WORD': ['.doc', '.docx'],
    'EXCEL': ['.xls', '.xlsx'],
    'IMAGEM': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'],
    'VIDEO': ['.mp4', '.avi', '.mov', '.wmv', '.mkv', '.webm'],
    'OUTRO': ['.txt', '.zip', '.rar', '.7z']
}

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB


def detectar_tipo_arquivo(filename):
    """Detecta o tipo de arquivo baseado na extensão"""
    ext = os.path.splitext(filename)[1].lower()
    
    for tipo, extensoes in ALLOWED_EXTENSIONS.items():
        if ext in extensoes:
            return tipo
    return 'OUTRO'


def validar_arquivo(file_obj):
    """Valida arquivo antes do upload"""
    errors = []
    
    # Validar tamanho
    if file_obj.size > MAX_FILE_SIZE:
        errors.append(f'Arquivo muito grande. Tamanho máximo: {MAX_FILE_SIZE / (1024*1024):.0f} MB')
    
    # Validar extensão
    ext = os.path.splitext(file_obj.name)[1].lower()
    todas_extensoes = [ext for exts in ALLOWED_EXTENSIONS.values() for ext in exts]
    if ext not in todas_extensoes:
        errors.append(f'Extensão não permitida: {ext}')
    
    return errors


def sanitizar_nome_arquivo(nome):
    """Remove caracteres perigosos do nome do arquivo"""
    nome = re.sub(r'[^\w\s\.-]', '', nome)
    nome = re.sub(r'\s+', ' ', nome)
    return nome.strip()


class RecordApoiaUploadView(APIView):
    """Upload de arquivos para Record Apoia"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            return Response({'error': 'Nenhum arquivo enviado'}, status=400)
        
        erros = validar_arquivo(arquivo)
        if erros:
            return Response({'error': '; '.join(erros)}, status=400)
        
        titulo = request.data.get('titulo', arquivo.name)
        descricao = request.data.get('descricao', '')
        categoria = request.data.get('categoria', '')
        tags = request.data.get('tags', '')
        tipo_arquivo = request.data.get('tipo_arquivo') or detectar_tipo_arquivo(arquivo.name)
        
        nome_original = sanitizar_nome_arquivo(arquivo.name)
        
        try:
            record_apoia = RecordApoia.objects.create(
                arquivo=arquivo,
                nome_original=nome_original,
                tipo_arquivo=tipo_arquivo,
                tamanho_bytes=arquivo.size,
                titulo=titulo[:255],
                descricao=descricao,
                categoria=categoria[:100] if categoria else None,
                tags=tags[:500] if tags else None,
                usuario_upload=request.user,
                ativo=True
            )
            
            return Response({
                'success': True,
                'id': record_apoia.id,
                'titulo': record_apoia.titulo,
                'tipo_arquivo': record_apoia.tipo_arquivo,
                'tamanho': record_apoia.formatar_tamanho(),
                'url': record_apoia.arquivo.url,
                'message': 'Arquivo enviado com sucesso!'
            }, status=201)
            
        except Exception as e:
            return Response({'error': f'Erro ao salvar arquivo: {str(e)}'}, status=500)


class RecordApoiaListView(APIView):
    """Lista arquivos do Record Apoia com filtros e busca"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        tipo_arquivo = request.GET.get('tipo_arquivo')
        categoria = request.GET.get('categoria')
        busca = request.GET.get('busca', '').strip()
        
        queryset = RecordApoia.objects.filter(ativo=True)
        
        if tipo_arquivo:
            queryset = queryset.filter(tipo_arquivo=tipo_arquivo)
        
        if categoria:
            queryset = queryset.filter(categoria__icontains=categoria)
        
        if busca:
            queryset = queryset.filter(
                Q(titulo__icontains=busca) |
                Q(descricao__icontains=busca) |
                Q(nome_original__icontains=busca) |
                Q(tags__icontains=busca)
            )
        
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        arquivos = queryset[start:end]
        
        dados = []
        for arquivo in arquivos:
            dados.append({
                'id': arquivo.id,
                'titulo': arquivo.titulo,
                'descricao': arquivo.descricao,
                'nome_original': arquivo.nome_original,
                'tipo_arquivo': arquivo.tipo_arquivo,
                'tipo_arquivo_display': arquivo.get_tipo_arquivo_display(),
                'categoria': arquivo.categoria,
                'tags': arquivo.tags,
                'tamanho_bytes': arquivo.tamanho_bytes,
                'tamanho_formatado': arquivo.formatar_tamanho(),
                'downloads_count': arquivo.downloads_count,
                'data_upload': arquivo.data_upload.isoformat() if arquivo.data_upload else None,
                'data_upload_formatada': arquivo.data_upload.strftime('%d/%m/%Y %H:%M') if arquivo.data_upload else None,
                'usuario_upload': arquivo.usuario_upload.get_full_name() if arquivo.usuario_upload else 'Sistema',
                'url': arquivo.arquivo.url if arquivo.arquivo else None,
            })
        
        categorias = RecordApoia.objects.filter(ativo=True).exclude(categoria__isnull=True).exclude(categoria='').values_list('categoria', flat=True).distinct()
        tipos = RecordApoia.objects.filter(ativo=True).values_list('tipo_arquivo', flat=True).distinct()
        
        return Response({
            'success': True,
            'arquivos': dados,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'categorias': list(categorias),
            'tipos': list(tipos),
        })


class RecordApoiaDownloadView(APIView):
    """Download de arquivo do Record Apoia"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, arquivo_id):
        try:
            record_apoia = RecordApoia.objects.get(id=arquivo_id, ativo=True)
            
            record_apoia.downloads_count += 1
            record_apoia.save(update_fields=['downloads_count'])
            
            arquivo = record_apoia.arquivo
            if not arquivo:
                return Response({'error': 'Arquivo não encontrado'}, status=404)
            
            response = FileResponse(arquivo.open('rb'), content_type='application/octet-stream')
            response['Content-Disposition'] = f'attachment; filename="{record_apoia.nome_original}"'
            return response
            
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            return Response({'error': f'Erro ao baixar arquivo: {str(e)}'}, status=500)


class RecordApoiaDeleteView(APIView):
    """Soft delete de arquivo (apenas Admin/Diretoria)"""
    permission_classes = [permissions.IsAuthenticated]
    
    def delete(self, request, arquivo_id):
        from crm_app.views import is_member
        
        if not is_member(request.user, ['Admin', 'Diretoria']):
            return Response({'error': 'Acesso negado'}, status=403)
        
        try:
            record_apoia = RecordApoia.objects.get(id=arquivo_id)
            record_apoia.ativo = False
            record_apoia.save(update_fields=['ativo'])
            
            return Response({
                'success': True,
                'message': 'Arquivo removido com sucesso'
            })
            
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            return Response({'error': f'Erro ao remover arquivo: {str(e)}'}, status=500)
