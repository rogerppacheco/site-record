import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from django.http import FileResponse, Http404
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from .models import RecordApoia
import os
from django.db.models import Q

logger = logging.getLogger(__name__)

class RecordApoiaUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Record Apoia é acessível a todos os usuários autenticados
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
                    
                    # Obter tamanho de forma segura
                    tamanho = 0
                    if record.arquivo:
                        try:
                            tamanho = record.arquivo.size
                        except (FileNotFoundError, IOError, OSError, AttributeError):
                            tamanho = 0
                    
                    resultados.append({
                        'id': record.id,
                        'titulo': record.titulo,
                        'nome_original': record.nome_original,
                        'tamanho': tamanho,
                        'tipo': record.get_tipo_arquivo_display(),
                        'criado_em': record.data_upload.isoformat() if record.data_upload else None
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
        # Record Apoia é acessível a todos os usuários autenticados
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
            
            queryset = queryset.order_by('-data_upload')
            
            # Importar settings para verificar caminho do arquivo
            from django.conf import settings
            from django.utils import timezone
            
            # Função auxiliar para formatar tamanho
            def formatar_tamanho_bytes(bytes_size):
                if bytes_size == 0:
                    return '0 Bytes'
                k = 1024
                sizes = ['Bytes', 'KB', 'MB', 'GB']
                i = 0
                size = float(bytes_size)
                while size >= k and i < len(sizes) - 1:
                    size /= k
                    i += 1
                return f"{round(size, 2)} {sizes[i]}"
            
            arquivos = []
            for arq in queryset:
                try:
                    # Verificar se o arquivo existe antes de adicionar à lista
                    arquivo_existe = False
                    tamanho = 0
                    
                    if arq.arquivo and arq.arquivo.name:
                        # Tentar verificar se o arquivo existe usando os.path.exists primeiro
                        try:
                            media_root = getattr(settings, 'MEDIA_ROOT', None)
                            if media_root:
                                caminho_completo = os.path.join(media_root, arq.arquivo.name)
                                arquivo_existe = os.path.exists(caminho_completo)
                            else:
                                # Se não tiver MEDIA_ROOT, usar storage
                                arquivo_existe = default_storage.exists(arq.arquivo.name)
                            
                            # Se existe, tentar obter tamanho
                            if arquivo_existe:
                                try:
                                    tamanho = arq.arquivo.size
                                except (FileNotFoundError, IOError, OSError, AttributeError) as size_error:
                                    # Arquivo pode ter sido removido entre a verificação e o acesso
                                    logger.warning(f"Arquivo {arq.id} existe mas erro ao obter tamanho: {size_error}")
                                    arquivo_existe = False
                                    tamanho = 0
                        except Exception as check_error:
                            # Erro ao verificar - considerar como não existente
                            logger.warning(f"Erro ao verificar arquivo {arq.id}: {check_error}")
                            arquivo_existe = False
                            tamanho = 0
                    
                    # Só adicionar arquivos que existem fisicamente
                    if arq.arquivo and arq.arquivo.name and not arquivo_existe:
                        # Arquivo não existe - marcar como inativo automaticamente
                        try:
                            arq.ativo = False
                            arq.save(update_fields=['ativo'])
                            logger.warning(f"Arquivo {arq.id} ({arq.titulo}) marcado como inativo - arquivo não encontrado no disco")
                        except Exception as deactivate_error:
                            logger.error(f"Erro ao marcar arquivo {arq.id} como inativo: {deactivate_error}")
                        continue  # Pular este arquivo
                    
                    # Se não tem arquivo definido, também pular (registro inválido)
                    if not arq.arquivo or not arq.arquivo.name:
                        continue
                    
                    # Formatar data
                    data_upload_formatada = None
                    if arq.data_upload:
                        data_upload_local = timezone.localtime(arq.data_upload)
                        data_upload_formatada = data_upload_local.strftime('%d/%m/%Y %H:%M')
                    
                    arquivos.append({
                        'id': arq.id,
                        'titulo': arq.titulo,
                        'descricao': arq.descricao,
                        'categoria': arq.categoria,
                        'tags': arq.tags,
                        'tipo_arquivo': arq.tipo_arquivo,  # Código do tipo (PDF, IMAGEM, etc.)
                        'tipo_arquivo_display': arq.get_tipo_arquivo_display(),  # Nome formatado
                        'tamanho_bytes': tamanho,  # Tamanho em bytes (para cálculos)
                        'tamanho_formatado': formatar_tamanho_bytes(tamanho),  # Tamanho formatado
                        'nome_original': arq.nome_original,
                        'downloads_count': arq.downloads_count,
                        'data_upload_formatada': data_upload_formatada,
                        'criado_em': arq.data_upload.isoformat() if arq.data_upload else None,  # Mantido para compatibilidade
                        'usuario_upload': arq.usuario_upload.username if arq.usuario_upload else None,
                        'url_download': f"/api/crm/record-apoia/{arq.id}/download/"
                    })
                except Exception as process_error:
                    # Erro ao processar um arquivo específico - logar e continuar
                    logger.error(f"Erro ao processar arquivo {arq.id}: {process_error}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue  # Pular este arquivo e continuar com os próximos
            
            # Calcular paginação
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            total = len(arquivos)
            total_pages = (total + page_size - 1) // page_size if total > 0 else 1
            
            # Aplicar paginação
            inicio = (page - 1) * page_size
            fim = inicio + page_size
            arquivos_paginados = arquivos[inicio:fim]
            
            return Response({
                'success': True,
                'total': total,
                'arquivos': arquivos_paginados,
                'page': page,
                'total_pages': total_pages
            })
            
        except Exception as e:
            logger.error(f"Erro ao listar arquivos: {e}")
            return Response({'error': str(e)}, status=500)


class RecordApoiaDownloadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, arquivo_id):
        # Record Apoia é acessível a todos os usuários autenticados
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
        # Record Apoia é acessível a todos os usuários autenticados
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
        # Record Apoia é acessível a todos os usuários autenticados
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
                existe_fisico = False
                caminho_completo = None
                
                if arquivo.arquivo and arquivo.arquivo.name:
                    caminho_relativo = arquivo.arquivo.name
                    media_root = getattr(settings, 'MEDIA_ROOT', None)
                    
                    if media_root:
                        caminho_completo = os.path.join(media_root, caminho_relativo)
                        existe_fisico = os.path.exists(caminho_completo)
                        
                        # Verificar pasta e listar arquivos reais
                        pasta = os.path.dirname(caminho_completo)
                        if pasta not in diagnosticos['pastas_verificadas']:
                            arquivos_reais = []
                            if os.path.exists(pasta):
                                try:
                                    arquivos_reais = [f for f in os.listdir(pasta) if os.path.isfile(os.path.join(pasta, f))]
                                except (PermissionError, OSError) as e:
                                    logger.warning(f"Erro ao listar pasta {pasta}: {e}")
                            
                            diagnosticos['pastas_verificadas'][pasta] = {
                                'existe': os.path.exists(pasta),
                                'arquivos_na_pasta': len(arquivos_reais),
                                'lista_arquivos': arquivos_reais  # Lista completa dos arquivos encontrados
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
                            'criado_em': arquivo.data_upload.isoformat() if arquivo.data_upload else None
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


class RecordApoiaCorrigirNomesView(APIView):
    """
    View para corrigir nomes de arquivos no banco que não correspondem aos arquivos no disco.
    Tenta encontrar os arquivos reais e atualizar os registros.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Record Apoia é acessível a todos os usuários autenticados
        try:
            from django.conf import settings
            import os
            import re
            
            media_root = getattr(settings, 'MEDIA_ROOT', None)
            if not media_root:
                return Response({'error': 'MEDIA_ROOT não configurado'}, status=500)
            
            # Buscar todos os arquivos ativos
            arquivos = RecordApoia.objects.filter(ativo=True)
            
            corrigidos = []
            erros = []
            
            for arquivo in arquivos:
                if not arquivo.arquivo or not arquivo.arquivo.name:
                    continue
                
                caminho_relativo = arquivo.arquivo.name
                pasta_relativa = os.path.dirname(caminho_relativo)
                nome_arquivo_banco = os.path.basename(caminho_relativo)
                nome_base = os.path.splitext(nome_arquivo_banco)[0]
                extensao = os.path.splitext(nome_arquivo_banco)[1]
                
                # Remover sufixos do Django (padrão: _XXXXXXXXX onde X são letras/números)
                nome_base_sem_sufixo = re.sub(r'_[A-Za-z0-9]{7,}$', '', nome_base)
                
                pasta_completa = os.path.join(media_root, pasta_relativa)
                
                if not os.path.exists(pasta_completa):
                    erros.append({
                        'id': arquivo.id,
                        'titulo': arquivo.titulo,
                        'erro': f'Pasta não existe: {pasta_completa}'
                    })
                    continue
                
                # Listar arquivos na pasta
                try:
                    arquivos_reais = [f for f in os.listdir(pasta_completa) if os.path.isfile(os.path.join(pasta_completa, f))]
                except (PermissionError, OSError) as e:
                    erros.append({
                        'id': arquivo.id,
                        'titulo': arquivo.titulo,
                        'erro': f'Erro ao listar pasta: {str(e)}'
                    })
                    continue
                
                # Tentar encontrar arquivo correspondente
                arquivo_encontrado = None
                
                # 1. Buscar pelo nome original (sem sufixo)
                for arq_real in arquivos_reais:
                    if os.path.splitext(arq_real)[0] == nome_base_sem_sufixo and os.path.splitext(arq_real)[1] == extensao:
                        arquivo_encontrado = arq_real
                        break
                
                # 2. Se não encontrou, buscar pelo nome original completo
                if not arquivo_encontrado:
                    for arq_real in arquivos_reais:
                        if arq_real == arquivo.nome_original:
                            arquivo_encontrado = arq_real
                            break
                
                # 3. Se ainda não encontrou, buscar qualquer arquivo com extensão igual
                if not arquivo_encontrado:
                    for arq_real in arquivos_reais:
                        if os.path.splitext(arq_real)[1] == extensao:
                            # Se só tem um arquivo com essa extensão, usar ele
                            arquivos_com_extensao = [a for a in arquivos_reais if os.path.splitext(a)[1] == extensao]
                            if len(arquivos_com_extensao) == 1:
                                arquivo_encontrado = arq_real
                                break
                
                if arquivo_encontrado:
                    novo_caminho_relativo = os.path.join(pasta_relativa, arquivo_encontrado).replace('\\', '/')
                    
                    # Atualizar o campo arquivo.name diretamente no banco
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE crm_app_recordapoia SET arquivo = %s WHERE id = %s",
                            [novo_caminho_relativo, arquivo.id]
                        )
                    
                    # Recarregar do banco
                    arquivo.refresh_from_db()
                    
                    corrigidos.append({
                        'id': arquivo.id,
                        'titulo': arquivo.titulo,
                        'nome_original': arquivo.nome_original,
                        'caminho_anterior': caminho_relativo,
                        'caminho_novo': novo_caminho_relativo,
                        'arquivo_encontrado': arquivo_encontrado
                    })
                else:
                    erros.append({
                        'id': arquivo.id,
                        'titulo': arquivo.titulo,
                        'nome_original': arquivo.nome_original,
                        'erro': 'Arquivo não encontrado na pasta',
                        'arquivos_disponiveis': arquivos_reais
                    })
            
            return Response({
                'sucesso': True,
                'corrigidos': corrigidos,
                'total_corrigidos': len(corrigidos),
                'erros': erros,
                'total_erros': len(erros)
            })
            
        except Exception as e:
            logger.error(f"Erro ao corrigir nomes: {e}")
            import traceback
            return Response({
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=500)
