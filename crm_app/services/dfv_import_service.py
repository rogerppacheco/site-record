"""
Serviço profissional para importação de arquivos DFV (Dados do Faturamento de Vendas).

Este módulo implementa as melhores práticas de desenvolvimento:
- Service Layer Pattern
- Logging estruturado
- Tratamento robusto de erros
- Gerenciamento eficiente de memória
- Progress tracking granular
- Validação de dados
- Transações atômicas
"""

import logging
import re
import traceback
from typing import Dict, List, Tuple, Optional, Set
from io import BytesIO
from datetime import datetime, timedelta

import pandas as pd
from django.db import transaction, connection
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError

from crm_app.models import DFV, LogImportacaoDFV

logger = logging.getLogger(__name__)


class DFVImportError(Exception):
    """Exceção customizada para erros de importação DFV"""
    pass


class DFVImportService:
    """
    Serviço profissional para processamento de importação DFV.
    
    Responsabilidades:
    - Validação de arquivos CSV
    - Processamento em chunks para otimização de memória
    - Remoção eficiente de duplicados
    - Criação em lote de registros
    - Tracking granular de progresso
    - Tratamento robusto de erros
    """
    
    # Constantes de configuração
    CHUNK_SIZE_CLEANUP = 100_000  # Tamanho do chunk para limpeza de dados
    CHUNK_SIZE_PREPARATION = 20_000  # Tamanho do chunk para preparação de objetos (reduzido para evitar travamento)
    BATCH_SIZE_DELETE = 10_000  # Tamanho do lote para remoção de duplicados
    BATCH_SIZE_CREATE = 1_000  # Tamanho do lote para criação de registros
    PROGRESS_UPDATE_INTERVAL = 5  # Atualizar progresso a cada N chunks
    PREPARATION_PROGRESS_INTERVAL = 5_000  # Atualizar progresso a cada N registros durante preparação
    
    # Colunas obrigatórias
    REQUIRED_COLUMNS = ['CEP', 'NUM_FACHADA']
    
    # Colunas opcionais
    OPTIONAL_COLUMNS = [
        'UF', 'MUNICIPIO', 'LOGRADOURO', 'COMPLEMENTO', 
        'BAIRRO', 'TIPO_VIABILIDADE', 'TIPO_REDE', 'CELULA', 'NOME_CDO'
    ]
    
    def __init__(self, log_id: int):
        """
        Inicializa o serviço de importação.
        
        Args:
            log_id: ID do log de importação
        """
        self.log_id = log_id
        self.log: Optional[LogImportacaoDFV] = None
        self._load_log()
        
    def _load_log(self) -> None:
        """Carrega o log de importação do banco de dados"""
        try:
            self.log = LogImportacaoDFV.objects.get(id=self.log_id)
        except LogImportacaoDFV.DoesNotExist:
            raise DFVImportError(f"Log de importação {self.log_id} não encontrado")
    
    def _update_progress(
        self, 
        total_processed: Optional[int] = None,
        success: Optional[int] = None,
        message: Optional[str] = None,
        errors: Optional[int] = None
    ) -> None:
        """
        Atualiza o progresso da importação de forma atômica.
        
        Args:
            total_processed: Total de registros processados
            success: Total de registros criados com sucesso
            message: Mensagem de status atual
            errors: Total de erros encontrados
        """
        update_fields = {}
        
        if total_processed is not None:
            update_fields['total_processadas'] = total_processed
        if success is not None:
            update_fields['sucesso'] = success
        if message is not None:
            update_fields['mensagem'] = message
        if errors is not None:
            update_fields['erros'] = errors
            
        if update_fields:
            try:
                LogImportacaoDFV.objects.filter(id=self.log_id).update(**update_fields)
            except Exception as e:
                logger.error(f"[DFV] Erro ao atualizar progresso: {e}", exc_info=True)
    
    def _validate_file(self, arquivo_bytes: bytes, arquivo_nome: str) -> None:
        """
        Valida o arquivo antes do processamento.
        
        Args:
            arquivo_bytes: Conteúdo do arquivo em bytes
            arquivo_nome: Nome do arquivo
            
        Raises:
            DFVImportError: Se o arquivo for inválido
        """
        if not arquivo_bytes:
            raise DFVImportError("Arquivo vazio")
        
        if not arquivo_nome.lower().endswith('.csv'):
            raise DFVImportError("Arquivo deve ter extensão .csv")
        
        # Validar tamanho mínimo (pelo menos alguns bytes)
        if len(arquivo_bytes) < 100:
            raise DFVImportError("Arquivo muito pequeno para ser válido")
        
        logger.info(f"[DFV] Arquivo validado: {arquivo_nome} ({len(arquivo_bytes) / (1024*1024):.2f} MB)")
    
    def _read_csv(self, arquivo_bytes: bytes) -> pd.DataFrame:
        """
        Lê o arquivo CSV com tratamento de encoding.
        
        Args:
            arquivo_bytes: Conteúdo do arquivo em bytes
            
        Returns:
            DataFrame do pandas com os dados
            
        Raises:
            DFVImportError: Se não conseguir ler o arquivo
        """
        arquivo_io = BytesIO(arquivo_bytes)
        
        # Tentar UTF-8 primeiro
        encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
        
        for encoding in encodings:
            try:
                arquivo_io.seek(0)
                df = pd.read_csv(
                    arquivo_io,
                    sep=';',
                    dtype=str,
                    encoding=encoding,
                    low_memory=False,
                    on_bad_lines='skip',
                    engine='c',
                    memory_map=False,
                    na_filter=False
                )
                logger.info(f"[DFV] Arquivo lido com sucesso usando encoding: {encoding}")
                return df
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error(f"[DFV] Erro ao ler CSV com encoding {encoding}: {e}")
                raise DFVImportError(f"Erro ao ler arquivo CSV: {str(e)}")
        
        raise DFVImportError("Não foi possível determinar o encoding do arquivo")
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normaliza os nomes das colunas do DataFrame.
        
        Args:
            df: DataFrame original
            
        Returns:
            DataFrame com colunas normalizadas
        """
        df.columns = [str(col).strip().upper() for col in df.columns]
        logger.debug(f"[DFV] Colunas normalizadas: {list(df.columns)[:10]}")
        return df
    
    def _validate_columns(self, df: pd.DataFrame) -> None:
        """
        Valida se as colunas obrigatórias estão presentes.
        
        Args:
            df: DataFrame a validar
            
        Raises:
            DFVImportError: Se colunas obrigatórias estiverem faltando
        """
        missing_columns = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing_columns:
            raise DFVImportError(
                f"Colunas obrigatórias não encontradas: {', '.join(missing_columns)}"
            )
    
    def _clean_cep(self, cep_str: str) -> str:
        """
        Limpa e normaliza um CEP, removendo caracteres não numéricos.
        
        Args:
            cep_str: String do CEP
            
        Returns:
            CEP limpo (apenas dígitos)
        """
        if not cep_str or pd.isna(cep_str):
            return ''
        return ''.join(filter(str.isdigit, str(cep_str)))
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Limpa e normaliza os dados do DataFrame.
        
        Args:
            df: DataFrame original
            
        Returns:
            DataFrame limpo com colunas cep_limpo e fachada_limpa
        """
        logger.info(f"[DFV] Iniciando limpeza de dados para {len(df)} registros")
        
        # Preencher NaN e converter para string
        df['CEP'] = df['CEP'].fillna('').astype(str)
        df['NUM_FACHADA'] = df['NUM_FACHADA'].fillna('').astype(str)
        
        # Processar em chunks para otimizar memória
        total_chunks = (len(df) + self.CHUNK_SIZE_CLEANUP - 1) // self.CHUNK_SIZE_CLEANUP
        
        df['cep_limpo'] = ''
        df['fachada_limpa'] = ''
        
        for i in range(0, len(df), self.CHUNK_SIZE_CLEANUP):
            chunk_num = (i // self.CHUNK_SIZE_CLEANUP) + 1
            end_idx = min(i + self.CHUNK_SIZE_CLEANUP, len(df))
            
            # Limpar CEP e fachada
            chunk_df = df.iloc[i:end_idx]
            df.loc[chunk_df.index, 'cep_limpo'] = chunk_df['CEP'].apply(self._clean_cep)
            df.loc[chunk_df.index, 'fachada_limpa'] = chunk_df['NUM_FACHADA'].str.strip()
            
            # Atualizar progresso periodicamente
            if chunk_num % self.PROGRESS_UPDATE_INTERVAL == 0:
                self._update_progress(
                    total_processed=end_idx,
                    message=f'Limpando dados... {chunk_num}/{total_chunks} chunks'
                )
                logger.debug(f"[DFV] Chunk {chunk_num}/{total_chunks} processado")
        
        logger.info(f"[DFV] Limpeza de dados concluída")
        return df
    
    def _filter_valid_rows(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        """
        Filtra linhas válidas (CEP e fachada não vazios).
        
        Args:
            df: DataFrame com dados limpos
            
        Returns:
            Tupla (DataFrame válido, número de linhas inválidas)
        """
        mask_valido = (df['cep_limpo'].str.len() > 0) & (df['fachada_limpa'].str.len() > 0)
        df_valido = df[mask_valido].copy()
        erros_count = (~mask_valido).sum()
        
        logger.info(
            f"[DFV] Linhas válidas: {len(df_valido)}/{len(df)} "
            f"(inválidas: {erros_count})"
        )
        
        return df_valido, int(erros_count)
    
    def _get_unique_pairs(self, df: pd.DataFrame) -> Set[Tuple[str, str]]:
        """
        Extrai pares únicos de (CEP, fachada).
        
        Args:
            df: DataFrame válido
            
        Returns:
            Set de tuplas (CEP, fachada)
        """
        logger.info("[DFV] Extraindo pares únicos (CEP, fachada)...")
        
        # Usar drop_duplicates para eficiência
        df_pares = df[['cep_limpo', 'fachada_limpa']].drop_duplicates()
        cep_fachada_set = set(
            zip(df_pares['cep_limpo'], df_pares['fachada_limpa'])
        )
        
        logger.info(f"[DFV] {len(cep_fachada_set)} pares únicos extraídos")
        return cep_fachada_set
    
    def _prepare_dfv_objects(
        self, 
        df: pd.DataFrame
    ) -> Tuple[List[DFV], int]:
        """
        Prepara objetos DFV a partir do DataFrame.
        
        Args:
            df: DataFrame válido
            
        Returns:
            Tupla (lista de objetos DFV, número de erros)
        """
        logger.info(f"[DFV] Preparando objetos DFV para {len(df)} registros...")
        
        registros_para_criar = []
        erros_count = 0
        erros_detalhados = []
        
        total_chunks = (len(df) + self.CHUNK_SIZE_PREPARATION - 1) // self.CHUNK_SIZE_PREPARATION
        
        processed_in_chunk = 0
        
        for chunk_idx in range(0, len(df), self.CHUNK_SIZE_PREPARATION):
            chunk_num = (chunk_idx // self.CHUNK_SIZE_PREPARATION) + 1
            chunk_df = df.iloc[chunk_idx:chunk_idx + self.CHUNK_SIZE_PREPARATION]
            
            logger.debug(
                f"[DFV] Processando chunk {chunk_num}/{total_chunks} "
                f"({len(chunk_df)} registros)..."
            )
            
            # Processar linha por linha com atualização de progresso mais frequente
            for row_idx, row_tuple in enumerate(chunk_df.itertuples(index=False)):
                try:
                    # Extrair valores
                    cep_val = getattr(row_tuple, 'cep_limpo', '')
                    fachada_val = getattr(row_tuple, 'fachada_limpa', '')
                    
                    # Extrair campos opcionais
                    optional_fields = {}
                    for col in self.OPTIONAL_COLUMNS:
                        if hasattr(row_tuple, col):
                            val = getattr(row_tuple, col, None)
                            if val and not pd.isna(val):
                                optional_fields[col.lower()] = str(val).strip()
                    
                    # Criar objeto DFV
                    obj = DFV(
                        cep=cep_val,
                        num_fachada=fachada_val,
                        **optional_fields
                    )
                    registros_para_criar.append(obj)
                    
                    processed_in_chunk += 1
                    total_processed_so_far = chunk_idx + processed_in_chunk
                    
                    # Atualizar progresso a cada N registros para mostrar que está progredindo
                    if processed_in_chunk % self.PREPARATION_PROGRESS_INTERVAL == 0:
                        self._update_progress(
                            total_processed=total_processed_so_far,
                            errors=erros_count,
                            message=f'Preparando objetos... {chunk_num}/{total_chunks} chunks ({total_processed_so_far}/{len(df)} registros)'
                        )
                        logger.debug(
                            f"[DFV] Chunk {chunk_num}/{total_chunks}: "
                            f"{processed_in_chunk}/{len(chunk_df)} registros processados no chunk, "
                            f"total: {len(registros_para_criar)} objetos preparados"
                        )
                    
                except Exception as e:
                    erros_count += 1
                    if len(erros_detalhados) < 10:
                        erros_detalhados.append(f"Erro ao criar objeto: {str(e)}")
                    logger.warning(f"[DFV] Erro ao criar objeto DFV: {e}")
            
            # Resetar contador para próximo chunk
            processed_in_chunk = 0
            
            # Atualizar progresso ao final de cada chunk
            total_processed_so_far = min(chunk_idx + self.CHUNK_SIZE_PREPARATION, len(df))
            self._update_progress(
                total_processed=total_processed_so_far,
                errors=erros_count,
                message=f'Preparando objetos... {chunk_num}/{total_chunks} chunks ({total_processed_so_far}/{len(df)} registros)'
            )
            
            logger.info(
                f"[DFV] Chunk {chunk_num}/{total_chunks} concluído. "
                f"Total de objetos preparados: {len(registros_para_criar)}"
            )
        
        logger.info(
            f"[DFV] Preparação concluída: {len(registros_para_criar)} objetos, "
            f"{erros_count} erros"
        )
        
        return registros_para_criar, erros_count
    
    def _remove_duplicates(self, cep_fachada_set: Set[Tuple[str, str]]) -> int:
        """
        Remove registros duplicados do banco de dados.
        
        Otimizado para usar sub-lotes menores e evitar queries OR gigantes
        que podem causar travamentos ou lentidão.
        
        Args:
            cep_fachada_set: Set de pares (CEP, fachada) únicos
            
        Returns:
            Número de registros removidos
        """
        total_no_banco = DFV.objects.count()
        
        if total_no_banco == 0:
            logger.info("[DFV] Banco vazio - pulando remoção de duplicados")
            return 0
        
        logger.info(
            f"[DFV] Iniciando remoção de duplicados. "
            f"Total no banco: {total_no_banco}, "
            f"Pares a verificar: {len(cep_fachada_set)}"
        )
        
        cep_fachada_list = list(cep_fachada_set)
        # Reduzir tamanho do lote para evitar queries OR muito grandes
        sub_batch_size = 500  # Processar 500 pares por vez dentro de cada transação
        total_lotes = (len(cep_fachada_list) + self.BATCH_SIZE_DELETE - 1) // self.BATCH_SIZE_DELETE
        registros_removidos = 0
        
        # Atualizar status inicial
        self._update_progress(
            message=f'Removendo duplicados... 0/{total_lotes} lotes'
        )
        
        for i in range(0, len(cep_fachada_list), self.BATCH_SIZE_DELETE):
            lote_num = (i // self.BATCH_SIZE_DELETE) + 1
            batch_cep_fachada = cep_fachada_list[i:i + self.BATCH_SIZE_DELETE]
            
            # Atualizar progresso antes de processar
            self._update_progress(
                message=f'Removendo duplicados... {lote_num}/{total_lotes} lotes ({registros_removidos} removidos)'
            )
            
            logger.info(
                f"[DFV] Processando lote {lote_num}/{total_lotes} "
                f"({len(batch_cep_fachada)} pares) em sub-lotes de {sub_batch_size}"
            )
            
            # Processar em sub-lotes menores para melhor performance
            for j in range(0, len(batch_cep_fachada), sub_batch_size):
                sub_batch = batch_cep_fachada[j:j + sub_batch_size]
                
                try:
                    # Usar query mais eficiente com sub-lotes menores
                    with transaction.atomic():
                        q_objects = Q()
                        for cep, fachada in sub_batch:
                            q_objects |= Q(cep=cep, num_fachada=fachada)
                        
                        if q_objects:
                            # Fazer count e delete em uma única query quando possível
                            # Usar .values_list() primeiro para identificar IDs pode ser mais rápido
                            # mas vamos manter simples por enquanto
                            count_sub = DFV.objects.filter(q_objects).count()
                            
                            if count_sub > 0:
                                DFV.objects.filter(q_objects).delete()
                                registros_removidos += count_sub
                                
                                if (j // sub_batch_size) % 10 == 0:  # Log a cada 10 sub-lotes
                                    logger.debug(
                                        f"[DFV] Lote {lote_num}/{total_lotes}, "
                                        f"sub-lote {j//sub_batch_size + 1}: "
                                        f"{count_sub} registros removidos "
                                        f"(total: {registros_removidos})"
                                    )
                
                except Exception as e:
                    logger.error(
                        f"[DFV] Erro ao remover duplicados no lote {lote_num}, "
                        f"sub-lote {j//sub_batch_size + 1}: {e}",
                        exc_info=True
                    )
                    # Continuar com próximo sub-lote mesmo em caso de erro
                    
                    # Tentar remover um por um como fallback para este sub-lote
                    logger.warning(
                        f"[DFV] Tentando remoção individual para sub-lote com erro..."
                    )
                    for cep, fachada in sub_batch:
                        try:
                            with transaction.atomic():
                                deleted = DFV.objects.filter(cep=cep, num_fachada=fachada).delete()[0]
                                registros_removidos += deleted
                        except Exception as e2:
                            logger.warning(
                                f"[DFV] Erro ao remover CEP={cep}, fachada={fachada}: {e2}"
                            )
            
            # Atualizar progresso após processar o lote completo
            self._update_progress(
                message=f'Removendo duplicados... {lote_num}/{total_lotes} lotes ({registros_removidos} removidos)'
            )
            
            logger.info(
                f"[DFV] Lote {lote_num}/{total_lotes} concluído. "
                f"Total removido até agora: {registros_removidos}"
            )
        
        logger.info(f"[DFV] Remoção de duplicados concluída: {registros_removidos} removidos")
        return registros_removidos
    
    def _create_records(
        self, 
        registros_para_criar: List[DFV]
    ) -> Tuple[int, int]:
        """
        Cria registros no banco de dados em lotes.
        
        Args:
            registros_para_criar: Lista de objetos DFV para criar
            
        Returns:
            Tupla (número de sucessos, número de erros)
        """
        logger.info(f"[DFV] Iniciando criação de {len(registros_para_criar)} registros...")
        
        sucesso_count = 0
        erros_count = 0
        erros_detalhados = []
        
        total_batches = (len(registros_para_criar) + self.BATCH_SIZE_CREATE - 1) // self.BATCH_SIZE_CREATE
        
        self._update_progress(
            message=f'Criando registros... 0/{total_batches} lotes'
        )
        
        for i in range(0, len(registros_para_criar), self.BATCH_SIZE_CREATE):
            batch_num = (i // self.BATCH_SIZE_CREATE) + 1
            batch = registros_para_criar[i:i + self.BATCH_SIZE_CREATE]
            
            try:
                # Tentar bulk_create primeiro
                with transaction.atomic():
                    DFV.objects.bulk_create(batch, ignore_conflicts=False)
                
                sucesso_count += len(batch)
                
                # Atualizar progresso
                self._update_progress(
                    success=sucesso_count,
                    message=f'Criando registros... {batch_num}/{total_batches} lotes ({sucesso_count} criados)'
                )
                
                if batch_num % self.PROGRESS_UPDATE_INTERVAL == 0:
                    logger.debug(
                        f"[DFV] Lote {batch_num}/{total_batches}: "
                        f"{sucesso_count}/{len(registros_para_criar)} registros criados"
                    )
                    
            except Exception as e:
                logger.warning(
                    f"[DFV] Erro no bulk_create (lote {batch_num}): {e}. "
                    f"Tentando inserção individual..."
                )
                
                # Fallback: inserir um por um
                for obj in batch:
                    try:
                        with transaction.atomic():
                            obj.save()
                        sucesso_count += 1
                    except Exception as e2:
                        erros_count += 1
                        if len(erros_detalhados) < 100:
                            erros_detalhados.append(
                                f"CEP={obj.cep} fachada={obj.num_fachada}: {str(e2)}"
                            )
                
                # Atualizar progresso mesmo com erros
                self._update_progress(
                    success=sucesso_count,
                    errors=erros_count,
                    message=f'Criando registros... {batch_num}/{total_batches} lotes ({sucesso_count} criados, {erros_count} erros)'
                )
        
        logger.info(
            f"[DFV] Criação concluída: {sucesso_count} sucessos, {erros_count} erros"
        )
        
        return sucesso_count, erros_count
    
    def _finalize_log(
        self,
        sucesso_count: int,
        erros_count: int,
        registros_removidos: int,
        erros_detalhados: List[str]
    ) -> None:
        """
        Finaliza o log de importação com os resultados.
        
        Args:
            sucesso_count: Número de registros criados com sucesso
            erros_count: Número de erros
            registros_removidos: Número de duplicados removidos
            erros_detalhados: Lista de mensagens de erro detalhadas
        """
        finalizado_em = timezone.now()
        
        # Calcular duração
        if self.log and self.log.iniciado_em:
            delta = finalizado_em - self.log.iniciado_em
            duracao_segundos = int(delta.total_seconds())
        else:
            duracao_segundos = 0
        
        # Preparar mensagens
        mensagem_erro_final = None
        if erros_detalhados:
            mensagem_erro_final = '\n'.join(erros_detalhados[:100])
            if len(erros_detalhados) > 100:
                mensagem_erro_final += f"\n... e mais {len(erros_detalhados) - 100} erros"
        
        # Determinar status final
        if erros_count > 0 and sucesso_count == 0:
            status_final = 'ERRO'
            mensagem_final = None
            if mensagem_erro_final:
                mensagem_erro_final += '\nNenhum registro foi importado com sucesso.'
        elif erros_count > 0:
            status_final = 'PARCIAL'
            mensagem_final = (
                f'Importação concluída parcialmente: {sucesso_count} registros importados '
                f'com sucesso, {erros_count} erros. {registros_removidos} registros duplicados removidos.'
            )
        else:
            status_final = 'SUCESSO'
            mensagem_final = (
                f'Importação concluída com sucesso: {sucesso_count} registros importados. '
                f'{registros_removidos} registros duplicados removidos e atualizados.'
            )
        
        # Atualizar log
        update_data = {
            'finalizado_em': finalizado_em,
            'duracao_segundos': duracao_segundos,
            'sucesso': sucesso_count,
            'erros': erros_count,
            'status': status_final,
        }
        
        if mensagem_final:
            update_data['mensagem'] = mensagem_final
        if mensagem_erro_final:
            update_data['mensagem_erro'] = mensagem_erro_final
        
        LogImportacaoDFV.objects.filter(id=self.log_id).update(**update_data)
        
        logger.info(
            f"[DFV] Importação finalizada - Log {self.log_id}: "
            f"status={status_final}, sucesso={sucesso_count}, "
            f"erros={erros_count}, removidos={registros_removidos}, "
            f"duração={duracao_segundos}s"
        )
    
    def process(self, arquivo_bytes: bytes, arquivo_nome: str) -> Dict:
        """
        Processa a importação completa do arquivo DFV.
        
        Este é o método principal que orquestra todo o processo:
        1. Validação do arquivo
        2. Leitura e normalização
        3. Limpeza de dados
        4. Remoção de duplicados
        5. Criação de registros
        
        Args:
            arquivo_bytes: Conteúdo do arquivo em bytes
            arquivo_nome: Nome do arquivo
            
        Returns:
            Dicionário com resultados da importação
            
        Raises:
            DFVImportError: Em caso de erro crítico
        """
        inicio = timezone.now()
        erros_detalhados = []
        
        try:
            # Atualizar status inicial
            LogImportacaoDFV.objects.filter(id=self.log_id).update(status='PROCESSANDO')
            logger.info(f"[DFV] Iniciando processamento - Log ID: {self.log_id}")
            
            # ETAPA 1: Validação
            self._validate_file(arquivo_bytes, arquivo_nome)
            
            # ETAPA 2: Leitura do CSV
            self._update_progress(message='Lendo arquivo CSV...')
            df = self._read_csv(arquivo_bytes)
            
            # ETAPA 3: Normalização de colunas
            df = self._normalize_columns(df)
            self._validate_columns(df)
            
            # Atualizar total de registros
            total_registros = len(df)
            LogImportacaoDFV.objects.filter(id=self.log_id).update(
                total_registros=total_registros,
                total_processadas=0,
                sucesso=0,
                tamanho_arquivo=len(arquivo_bytes)
            )
            logger.info(f"[DFV] Total de registros no arquivo: {total_registros}")
            
            # ETAPA 4: Limpeza de dados
            self._update_progress(message='Limpando e normalizando dados...')
            df = self._clean_data(df)
            
            # ETAPA 5: Filtragem de linhas válidas
            df_valido, erros_invalidos = self._filter_valid_rows(df)
            erros_detalhados.extend(
                [f"Linha inválida: CEP ou fachada vazio"] * min(erros_invalidos, 10)
            )
            
            # Liberar memória do DataFrame original
            del df
            
            # ETAPA 6: Extração de pares únicos
            self._update_progress(message='Extraindo pares únicos...')
            cep_fachada_set = self._get_unique_pairs(df_valido)
            
            # ETAPA 7: Preparação de objetos
            self._update_progress(message='Preparando objetos DFV...')
            registros_para_criar, erros_preparacao = self._prepare_dfv_objects(df_valido)
            erros_detalhados.extend(
                [f"Erro ao preparar objeto"] * min(erros_preparacao, 10)
            )
            
            # Liberar memória do DataFrame válido
            del df_valido
            
            # ETAPA 8: Remoção de duplicados
            self._update_progress(message='Removendo registros duplicados...')
            registros_removidos = self._remove_duplicates(cep_fachada_set)
            
            # Liberar memória do set
            del cep_fachada_set
            
            # ETAPA 9: Criação de registros
            self._update_progress(message='Criando registros no banco de dados...')
            sucesso_count, erros_criacao = self._create_records(registros_para_criar)
            
            # Liberar memória da lista de objetos
            del registros_para_criar
            
            # ETAPA 10: Finalização
            self._finalize_log(
                sucesso_count=sucesso_count,
                erros_count=erros_invalidos + erros_preparacao + erros_criacao,
                registros_removidos=registros_removidos,
                erros_detalhados=erros_detalhados
            )
            
            return {
                'success': True,
                'log_id': self.log_id,
                'sucesso': sucesso_count,
                'erros': erros_invalidos + erros_preparacao + erros_criacao,
                'removidos': registros_removidos
            }
            
        except DFVImportError as e:
            logger.error(f"[DFV] Erro de importação: {e}", exc_info=True)
            self._handle_error(str(e))
            raise
            
        except Exception as e:
            logger.error(f"[DFV] Erro crítico inesperado: {e}", exc_info=True)
            self._handle_error(f"Erro fatal: {str(e)}")
            raise DFVImportError(f"Erro crítico: {str(e)}")
    
    def _handle_error(self, error_message: str) -> None:
        """
        Trata erros atualizando o log de importação.
        
        Args:
            error_message: Mensagem de erro
        """
        try:
            LogImportacaoDFV.objects.filter(id=self.log_id).update(
                status='ERRO',
                mensagem_erro=error_message,
                finalizado_em=timezone.now()
            )
        except Exception as e:
            logger.error(f"[DFV] Erro ao atualizar log de erro: {e}", exc_info=True)
