import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from django.http import FileResponse, Http404
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from .models import RecordApoia
from .utils import is_member
import os
from django.db.models import Q

logger = logging.getLogger(__name__)

class RecordApoiaUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not is_member(request.user):
            return Response({'error': 'Acesso negado'}, status=403)
        
        try:
            arquivos = request.FILES.getlist('arquivo')
            if not arquivos:
                return Response({'error': 'Nenhum arquivo enviado'}, status=400)
            
            titulo = request.data.get('titulo', '').strip()
            descricao = request.data.get('descricao', '').strip()
            categoria = request.data.get('categoria', '').strip()
            tags = request.data.get('tags', '').strip()
            
            resultados = []
            erros = []
            
            for arquivo in arquivos:
                try:
                    # Validar arquivo
                    if arquivo.size > 100 * 1024 * 1024:  # 100MB
                        erros.append({
                            'arquivo': arquivo.name,
                            'erro': 'Arquivo muito grande (máximo 100MB)'
                        })
                        continue
                    
                    # Usar o título fornecido ou o nome do arquivo
                    titulo_arquivo = titulo if titulo else arquivo.name
                    if len(arquivos) > 1 and titulo:
                        # Se múltiplos arquivos e título fornecido, usar título + nome do arquivo
                        titulo_arquivo = f"{titulo} - {arquivo.name}"
                    
                    # Criar registro
                    record = RecordApoia.objects.create(
                        titulo=titulo_arquivo,
                        descricao=descricao,
                        categoria=categoria,
                        tags=tags,
                        arquivo=arquivo,
                        nome_original=arquivo.name,
                        usuario_upload=request.user
                    )
                    
                    resultados.append({
                        'id': record.id,
                        'titulo': record.titulo,
                        'nome_original': record.nome_original,
                        'tamanho': record.arquivo.size if record.arquivo else 0,
                        'tipo': record.get_tipo_arquivo_display(),
                        'criado_em': record.criado_em.isoformat()
                    })
                except Exception as e:
                    logger.error(f"Erro ao fazer upload de {arquivo.name}: {e}")
                    erros.append({
                        'arquivo': arquivo.name,
                        'erro': str(e)
                    })
            
            if resultados and not erros:
                return Response({
                    'sucesso': True,
                    'resultados': resultados,
                    'total': len(resultados)
                }, status=201)
            elif resultados and erros:
                return Response({
                    'sucesso': True,
                    'resultados': resultados,
                    'erros': erros,
                    'total': len(resultados),
                    'total_erros': len(erros)
                }, status=207)  # Multi-Status
            else:
                return Response({
                    'sucesso': False,
                    'erros': erros
                }, status=400)
                
        except Exception as e:
            logger.error(f"Erro no upload: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user):
            return Response({'error': 'Acesso negado'}, status=403)
        
        try:
            busca = request.query_params.get('busca', '').strip()
            categoria_filtro = request.query_params.get('categoria', '').strip()
            
            queryset = RecordApoia.objects.filter(ativo=True)
            
            if busca:
                queryset = queryset.filter(
                    Q(titulo__icontains=busca) |
                    Q(descricao__icontains=busca) |
                    Q(tags__icontains=busca) |
                    Q(categoria__icontains=busca)
                )
            
            if categoria_filtro:
                queryset = queryset.filter(categoria__iexact=categoria_filtro)
            
            queryset = queryset.order_by('-criado_em')
            
            arquivos = []
            for arq in queryset:
                arquivos.append({
                    'id': arq.id,
                    'titulo': arq.titulo,
                    'descricao': arq.descricao,
                    'categoria': arq.categoria,
                    'tags': arq.tags,
                    'tipo': arq.get_tipo_arquivo_display(),
                    'tamanho': arq.arquivo.size if arq.arquivo else 0,
                    'nome_original': arq.nome_original,
                    'downloads_count': arq.downloads_count,
                    'criado_em': arq.criado_em.isoformat(),
                    'usuario_upload': arq.usuario_upload.username if arq.usuario_upload else None,
                    'url_download': f"/api/record-apoia/{arq.id}/download/"
                })
            
            return Response({
                'total': len(arquivos),
                'arquivos': arquivos
            })
            
        except Exception as e:
            logger.error(f"Erro ao listar arquivos: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaDownloadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, arquivo_id):
        if not is_member(request.user):
            return Response({'error': 'Acesso negado'}, status=403)
        
        try:
            arquivo = RecordApoia.objects.get(id=arquivo_id, ativo=True)
            arquivo.downloads_count += 1
            arquivo.save(update_fields=['downloads_count'])
            
            if not arquivo.arquivo:
                return Response({'error': 'Arquivo não encontrado'}, status=404)
            
            # Tentar abrir o arquivo
            try:
                arquivo.arquivo.open('rb')
                return FileResponse(arquivo.arquivo.open('rb'), as_attachment=True, filename=arquivo.nome_original)
            except (FileNotFoundError, IOError, OSError) as e:
                logger.error(f"Erro ao abrir arquivo {arquivo.arquivo.name}: {e}")
                # Tentar usar storage
                if default_storage.exists(arquivo.arquivo.name):
                    return FileResponse(default_storage.open(arquivo.arquivo.name, 'rb'), as_attachment=True, filename=arquivo.nome_original)
                else:
                    return Response({'error': f'Arquivo físico não encontrado: {arquivo.arquivo.name}'}, status=404)
                    
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro no download: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, arquivo_id):
        if not is_member(request.user):
            return Response({'error': 'Acesso negado'}, status=403)
        
        try:
            arquivo = RecordApoia.objects.get(id=arquivo_id)
            
            # Marcar como inativo (soft delete)
            arquivo.ativo = False
            arquivo.save()
            
            return Response({'sucesso': True, 'mensagem': 'Arquivo removido com sucesso'})
            
        except RecordApoia.DoesNotExist:
            return Response({'error': 'Arquivo não encontrado'}, status=404)
        except Exception as e:
            logger.error(f"Erro ao deletar: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaDiagnosticoView(APIView):
    """
    View para diagnosticar problemas com arquivos do Record Apoia.
    Verifica se os arquivos físicos existem no servidor.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user):
            return Response({'error': 'Acesso negado'}, status=403)
        
        try:
            from django.conf import settings
            import os
            
            # Buscar todos os arquivos ativos
            arquivos = RecordApoia.objects.filter(ativo=True)
            
            diagnosticos = {
                'total_arquivos': arquivos.count(),
                'arquivos_com_problema': [],
                'arquivos_ok': 0,
                'pastas_verificadas': {},
                'media_root': getattr(settings, 'MEDIA_ROOT', 'Não configurado')
            }
            
            for arquivo in arquivos:
                arquivo_path = None
                existe_fisico = False
                caminho_completo = None
                
                if arquivo.arquivo and arquivo.arquivo.name:
                    caminho_relativo = arquivo.arquivo.name
                    media_root = getattr(settings, 'MEDIA_ROOT', None)
                    
                    if media_root:
                        caminho_completo = os.path.join(media_root, caminho_relativo)
                        existe_fisico = os.path.exists(caminho_completo)
                        
                        # Verificar pasta
                        pasta = os.path.dirname(caminho_completo)
                        if pasta not in diagnosticos['pastas_verificadas']:
                            diagnosticos['pastas_verificadas'][pasta] = {
                                'existe': os.path.exists(pasta),
                                'arquivos_na_pasta': len([f for f in os.listdir(pasta) if os.path.isfile(os.path.join(pasta, f))]) if os.path.exists(pasta) else 0
                            }
                    else:
                        # Tentar usar storage
                        existe_fisico = default_storage.exists(caminho_relativo)
                        caminho_completo = caminho_relativo
                    
                    if existe_fisico:
                        diagnosticos['arquivos_ok'] += 1
                    else:
                        diagnosticos['arquivos_com_problema'].append({
                            'id': arquivo.id,
                            'titulo': arquivo.titulo,
                            'nome_original': arquivo.nome_original,
                            'caminho_esperado': caminho_completo,
                            'caminho_relativo': caminho_relativo,
                            'criado_em': arquivo.criado_em.isoformat()
                        })
            
            diagnosticos['total_com_problema'] = len(diagnosticos['arquivos_com_problema'])
            
            return Response(diagnosticos)
            
        except Exception as e:
            logger.error(f"Erro no diagnóstico: {e}")
            import traceback
            return Response({
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=500)
