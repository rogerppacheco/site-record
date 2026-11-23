"""Chave do importador FPD/SPD: zeros à esquerda e match_status."""

from datetime import datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from crm_app.services.fpd_import_service import (
    MATCH_FALTA_CRM,
    MATCH_MATCHED,
    MATCH_ORFAO,
    buscar_importacao_indexada,
    indexar_importacoes,
    match_status_para_contrato,
    normalizar_digitos_chave,
)


def _imp(**kwargs):
    base = dict(
        id=1,
        pk=1,
        nr_ordem='10039185',
        indicador='SPD',
        nr_fatura='11705444753',
        id_contrato='2812957',
        ds_sit_fatura='',
        municipio='',
        nm_pdv='',
        contrato_m10_id=None,
        contrato_m10=None,
        atualizada_em=datetime(2026, 8, 26, tzinfo=timezone.utc),
        importada_em=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    base['pk'] = base['id']
    return SimpleNamespace(**base)


class ChaveImportacaoFpdTest(SimpleTestCase):
    def test_remove_zeros_a_esquerda(self):
        self.assertEqual(normalizar_digitos_chave('02812957'), '2812957')
        self.assertEqual(normalizar_digitos_chave('09984987'), '9984987')
        self.assertEqual(normalizar_digitos_chave('10039185'), '10039185')
        self.assertEqual(normalizar_digitos_chave(''), '')

    def test_mesma_fatura_com_zero_na_os_nao_duplica(self):
        antiga = _imp(
            id=12962,
            nr_ordem='10039185',
            id_contrato='02812957',
            ds_sit_fatura='FECHADA',
            municipio='CONTAGEM',
            nm_pdv='RECORD',
            atualizada_em=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        esparsa = _imp(
            id=21643,
            nr_ordem='10039185',
            id_contrato='2812957',
            ds_sit_fatura='',
            municipio='',
            contrato_m10_id=13681,
            atualizada_em=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )
        indice = indexar_importacoes([esparsa, antiga])
        achou = buscar_importacao_indexada(
            indice, '10039185', 'SPD', '11705444753', '02812957',
        )
        self.assertIs(achou, antiga)

        outra_fatura = buscar_importacao_indexada(
            indice, '09984987', 'SPD', '999000111', '02797033',
        )
        self.assertIsNone(outra_fatura)

    def test_os_com_zero_e_a_mesma_fatura(self):
        portal = _imp(
            id=20206,
            nr_ordem='09984987',
            id_contrato='02797033',
            nr_fatura='11801344369',
            ds_sit_fatura='FECHADA',
            municipio='BH',
            nm_pdv='RECORD',
        )
        planilha = _imp(
            id=23277,
            nr_ordem='9984987',
            id_contrato='2797033',
            nr_fatura='11801344369',
            ds_sit_fatura='',
        )
        indice = indexar_importacoes([planilha, portal])
        achou = buscar_importacao_indexada(
            indice, '9984987', 'SPD', '11801344369', '2797033',
        )
        self.assertIs(achou, portal)

    def test_faturas_diferentes_da_mesma_os_nao_se_fundem(self):
        fpd = _imp(id=1, indicador='FPD', nr_fatura='111', id_contrato='2812957')
        spd = _imp(id=2, indicador='SPD', nr_fatura='222', id_contrato='02812957')
        indice = indexar_importacoes([fpd, spd])
        self.assertIs(
            buscar_importacao_indexada(indice, '10039185', 'FPD', '111', '2812957'),
            fpd,
        )
        self.assertIs(
            buscar_importacao_indexada(indice, '10039185', 'SPD', '222', '02812957'),
            spd,
        )

    def test_match_status(self):
        self.assertEqual(match_status_para_contrato(None), MATCH_FALTA_CRM)
        contrato = SimpleNamespace(orfao=False)
        self.assertEqual(match_status_para_contrato(contrato), MATCH_MATCHED)
        orfao = SimpleNamespace(orfao=True)
        self.assertEqual(match_status_para_contrato(orfao), MATCH_MATCHED)
        self.assertEqual(
            match_status_para_contrato(orfao, sem_contrato_real=True),
            MATCH_ORFAO,
        )
        self.assertEqual(
            match_status_para_contrato(None, sem_contrato_real=True),
            MATCH_FALTA_CRM,
        )
