# -*- coding: utf-8 -*-
from django.test import SimpleTestCase, TestCase

from crm_app.models import ConfigIsencaoBoletoVolume
from crm_app.services.isencao_boleto_volume_service import (
    deve_isentar_desconto_boleto_por_volume,
    get_config_isencao_boleto_volume,
)


class DeveIsentarDescontoBoletoPorVolumeUnitTest(SimpleTestCase):
    def test_abaixo_do_limiar_nao_isenta(self):
        cfg = ConfigIsencaoBoletoVolume(ativo=True, min_vendas_instaladas=30)
        self.assertFalse(deve_isentar_desconto_boleto_por_volume(29, config=cfg))

    def test_igual_ao_limiar_isenta(self):
        cfg = ConfigIsencaoBoletoVolume(ativo=True, min_vendas_instaladas=30)
        self.assertTrue(deve_isentar_desconto_boleto_por_volume(30, config=cfg))

    def test_acima_do_limiar_isenta(self):
        cfg = ConfigIsencaoBoletoVolume(ativo=True, min_vendas_instaladas=30)
        self.assertTrue(deve_isentar_desconto_boleto_por_volume(45, config=cfg))

    def test_regra_desligada_nao_isenta(self):
        cfg = ConfigIsencaoBoletoVolume(ativo=False, min_vendas_instaladas=30)
        self.assertFalse(deve_isentar_desconto_boleto_por_volume(50, config=cfg))

    def test_limiar_customizado(self):
        cfg = ConfigIsencaoBoletoVolume(ativo=True, min_vendas_instaladas=40)
        self.assertFalse(deve_isentar_desconto_boleto_por_volume(39, config=cfg))
        self.assertTrue(deve_isentar_desconto_boleto_por_volume(40, config=cfg))


class ConfigIsencaoBoletoVolumePersistenciaTest(TestCase):
    def test_get_cria_singleton_padrao(self):
        ConfigIsencaoBoletoVolume.objects.all().delete()
        cfg = get_config_isencao_boleto_volume()
        self.assertTrue(cfg.ativo)
        self.assertEqual(cfg.min_vendas_instaladas, 30)
        self.assertEqual(ConfigIsencaoBoletoVolume.objects.count(), 1)
        cfg2 = get_config_isencao_boleto_volume()
        self.assertEqual(cfg.id, cfg2.id)
