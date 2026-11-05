"""Funil de vendas: perfil Vendedor não entra; permissão explícita libera outro perfil."""
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase

from crm_app.models import Venda
from crm_app.perfis_acesso import pode_ver_funil_vendas
from usuarios.models import Perfil, Usuario


def _limpar_cache_perm(usuario):
    for cache in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
        if hasattr(usuario, cache):
            delattr(usuario, cache)


def _conceder_funil(usuario):
    ct = ContentType.objects.get_for_model(Venda)
    perm = Permission.objects.get(codename='can_view_funil_vendas', content_type=ct)
    grupo, _ = Group.objects.get_or_create(name=f'perm-funil-{usuario.username}')
    grupo.permissions.add(perm)
    usuario.groups.add(grupo)
    _limpar_cache_perm(usuario)


class FunilAcessoPerfilTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil_vend = Perfil.objects.create(cod_perfil='VEND_FUNIL', nome='Vendedor')
        cls.perfil_interno = Perfil.objects.create(cod_perfil='VEND_INT', nome='Vendedor Interno')
        cls.perfil_bo = Perfil.objects.create(cod_perfil='BO_FUNIL', nome='BackOffice')
        cls.vendedor = Usuario.objects.create_user(
            username='vend_funil',
            password='SenhaSegura123',
            perfil=cls.perfil_vend,
        )
        cls.interno = Usuario.objects.create_user(
            username='vend_interno',
            password='SenhaSegura123',
            perfil=cls.perfil_interno,
        )
        cls.backoffice = Usuario.objects.create_user(
            username='bo_funil',
            password='SenhaSegura123',
            perfil=cls.perfil_bo,
        )
        Group.objects.get_or_create(name='Vendedor')[0].user_set.add(cls.vendedor)
        Group.objects.get_or_create(name='Vendedor Interno')[0].user_set.add(cls.interno)
        Group.objects.get_or_create(name='BackOffice')[0].user_set.add(cls.backoffice)

    def test_vendedor_nao_ve_funil(self):
        self.assertFalse(pode_ver_funil_vendas(self.vendedor))
        self.client.force_authenticate(user=self.vendedor)
        resp = self.client.get('/api/crm/funil-venda-wpp/tentativas/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_vendedor_com_permissao_marcada_continua_sem_acesso(self):
        _conceder_funil(self.vendedor)
        self.assertFalse(pode_ver_funil_vendas(self.vendedor))
        self.client.force_authenticate(user=self.vendedor)
        resp = self.client.get('/api/crm/funil-venda-wpp/tentativas/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_vendedor_interno_sem_permissao_nao_acessa(self):
        self.assertFalse(pode_ver_funil_vendas(self.interno))
        self.client.force_authenticate(user=self.interno)
        resp = self.client.get('/api/crm/funil-venda-wpp/tentativas/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_vendedor_interno_com_permissao_acessa(self):
        _conceder_funil(self.interno)
        self.assertTrue(pode_ver_funil_vendas(self.interno))
        self.client.force_authenticate(user=self.interno)
        resp = self.client.get('/api/crm/funil-venda-wpp/tentativas/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_backoffice_continua_no_modulo_sem_permissao_extra(self):
        self.assertTrue(pode_ver_funil_vendas(self.backoffice))
        self.client.force_authenticate(user=self.backoffice)
        resp = self.client.get('/api/crm/funil-tratar/')
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
