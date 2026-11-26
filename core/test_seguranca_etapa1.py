"""Etapa 1: segredo da verificação em duas etapas cifrado em repouso e relatório de CPFs repetidos."""
from io import StringIO
from types import SimpleNamespace

from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings

from core import cifragem
from core.dois_fatores import novo_segredo
from core.models import Usuario


def _bruto(pk):
    with connection.cursor() as c:
        c.execute("SELECT totp_segredo FROM core_usuario WHERE id = %s", [pk])
        return c.fetchone()[0]


class SegredoCifradoTests(TestCase):
    def setUp(self):
        self.u = Usuario.objects.create(username="pessoa.teste", nome_completo="Pessoa Teste", papel="ORIENTADOR")
        self.segredo = novo_segredo()

    def test_gravado_cifrado_lido_em_claro(self):
        Usuario.objects.filter(pk=self.u.pk).update(totp_segredo=self.segredo)
        bruto = _bruto(self.u.pk)
        self.assertTrue(bruto.startswith(cifragem.PREFIXO))
        self.assertNotIn(self.segredo, bruto)
        self.assertEqual(Usuario.objects.get(pk=self.u.pk).totp_segredo, self.segredo)
        self.assertTrue(Usuario.objects.exclude(totp_segredo="").filter(pk=self.u.pk).exists())

    def test_vazio_continua_vazio(self):
        self.u.totp_segredo = ""
        self.u.save()
        self.assertEqual(_bruto(self.u.pk), "")

    def test_migration_ida_e_volta(self):
        from importlib import import_module

        mig = import_module("core.migrations.0046_segredo_2fa_cifrado")
        with connection.cursor() as c:  # valor antigo, em claro
            c.execute("UPDATE core_usuario SET totp_segredo = %s WHERE id = %s", [self.segredo, self.u.pk])
        self.assertEqual(Usuario.objects.get(pk=self.u.pk).totp_segredo, self.segredo)  # lido mesmo em claro
        editor = SimpleNamespace(connection=connection)  # a função só usa editor.connection
        mig.cifrar(apps, editor)
        self.assertTrue(_bruto(self.u.pk).startswith(cifragem.PREFIXO))
        mig.cifrar(apps, editor)  # rodar de novo não cifra duas vezes
        self.assertEqual(Usuario.objects.get(pk=self.u.pk).totp_segredo, self.segredo)
        mig.decifrar(apps, editor)
        self.assertEqual(_bruto(self.u.pk), self.segredo)

    def test_troca_de_chave_com_lista(self):
        from cryptography.fernet import Fernet

        velha, nova = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(CHAVE_DADOS=velha):
            Usuario.objects.filter(pk=self.u.pk).update(totp_segredo=self.segredo)
        with override_settings(CHAVE_DADOS=f"{nova},{velha}"):
            self.assertEqual(Usuario.objects.get(pk=self.u.pk).totp_segredo, self.segredo)
            call_command("chave_dados", "--recifrar", stdout=StringIO())
        with override_settings(CHAVE_DADOS=nova):
            self.assertEqual(Usuario.objects.get(pk=self.u.pk).totp_segredo, self.segredo)
        with override_settings(CHAVE_DADOS=velha), self.assertRaises(ValueError):
            Usuario.objects.get(pk=self.u.pk).totp_segredo  # noqa: B018


class RelatorioCpfTests(TestCase):
    def test_repetidos_e_invalidos_sem_mostrar_cpf(self):
        cpf = "529.982.247-25"  # CPF válido de exemplo (gerador), fictício
        a = Usuario.objects.create(username="a.a", nome_completo="Pessoa A", papel="SUPERVISOR", cpf=cpf)
        b = Usuario.objects.create(username="b.b", nome_completo="Pessoa B", papel="RESPONSAVEL", cpf="52998224725")
        Usuario.objects.create(username="c.c", nome_completo="Pessoa C", papel="ESTAGIARIO", cpf="111.111.111-11")
        saida = StringIO()
        call_command("relatorio_cpf", stdout=saida)
        texto = saida.getvalue()
        self.assertIn("1 CPF(s) em mais de uma conta", texto)
        self.assertIn(f"#{a.pk} supervisor", texto)
        self.assertIn(f"#{b.pk} responsavel", texto)
        self.assertIn("1 conta(s) com CPF inválido", texto)
        self.assertNotIn("529", texto)
        self.assertNotIn("Pessoa", texto)
