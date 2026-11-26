"""O que muda entre o SQLite e o PostgreSQL: conexões das threads, maiúsculas, vazios na ordenação e NUL.

Roda nos dois bancos (ver docs/operacao/migracao-postgresql.md, “Diferenças entre o SQLite e o PostgreSQL”)."""
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Agendamento, Configuracao, RegistroAcao, Sugestao, Usuario, nome_municipio
from .tests import Base


class ThreadsTests(Base):
    def test_a_thread_fecha_as_proprias_conexoes_mesmo_com_erro(self):
        from . import threads

        fechou_em = []

        def falha():
            raise RuntimeError("falha de propósito")

        with mock.patch.object(threads, "fechar_conexoes_da_thread", lambda: fechou_em.append(threading.get_ident())), \
                mock.patch("threading.excepthook"):  # o erro de propósito não suja a saída
            t = threads.iniciar_thread(falha)
            t.join(5)
        self.assertEqual(fechou_em, [t.ident])
        self.assertNotEqual(t.ident, threading.get_ident())

    def test_a_thread_leva_o_contexto(self):
        import contextvars

        from .threads import iniciar_thread

        var = contextvars.ContextVar("var_teste", default="fora")
        var.set("dentro")
        visto = []
        iniciar_thread(lambda: visto.append(var.get())).join(5)
        self.assertEqual(visto, ["dentro"])

    def test_aguardar_threads(self):
        from .threads import aguardar_threads, iniciar_thread

        t = iniciar_thread(lambda: time.sleep(0.2))
        self.assertEqual(aguardar_threads(5), 0)
        self.assertFalse(t.is_alive())

    @override_settings(EMAIL_ASSINCRONO=False, EMAIL_ATIVO=True)
    def test_caminho_sincrono_nao_fecha_a_conexao_de_quem_chamou(self):
        """O erro “the connection is closed” do PostgreSQL: sem thread, nada pode fechar a conexão da requisição."""
        from . import sugestoes
        from .acompanhamento import disparar_resumo_se_preciso
        from .services import enviar_emails

        tz = timezone.get_current_timezone()
        Configuracao.atual()
        Configuracao.objects.update(resumo_enviado_em=datetime(2026, 11, 3, 9, 0, tzinfo=tz))
        s = Sugestao.objects.create(nome="Teste", mensagem="Teste de envio")
        with mock.patch.object(connections, "close_all") as fechar, \
                mock.patch("core.sugestoes.destinatarios", return_value=["dev@exemplo.br"]):
            self.assertTrue(disparar_resumo_se_preciso(datetime(2026, 11, 9, 8, 0, tzinfo=tz)))
            enviar_emails([("Assunto", "Corpo", "sistema@exemplo.br", ["ori@exemplo.br"])])
            sugestoes.enviar(s.pk, assincrono=False)
        fechar.assert_not_called()
        connection.ensure_connection()
        self.assertTrue(connection.is_usable())
        self.assertGreater(Usuario.objects.count(), 0)


class NomeMunicipioTests(SimpleTestCase):
    def test_formata_maiusculas_e_tira_a_uf(self):
        casos = {
            "GENERAL SAMPAIO - CE": "General Sampaio",
            "são gonçalo do amarante/ce": "São Gonçalo do Amarante",
            "ITAPAJÉ (CE)": "Itapajé",
            "  PAU D'ARCO  ": "Pau D'Arco",
            "Juazeiro do Norte": "Juazeiro do Norte",  # já escrito com cuidado: fica como está
            "": "",
        }
        for entrada, esperado in casos.items():
            self.assertEqual(nome_municipio(entrada), esperado, entrada)


class DiferencasDeBancoTests(Base):
    def test_busca_por_ip_no_registro_de_acoes_ignora_maiusculas(self):
        admin = Usuario.objects.create_superuser("admin", "admin@example.com", "Senha#Admin9", nome_completo="Ana Admin")
        admin.deve_trocar_senha = False
        admin.save()
        RegistroAcao.objects.create(tipo="teste", descricao="Ação do IPv6", ip="2804:abcd::1")
        self.entrar(admin)
        self.assertContains(self.client.get(reverse("registro_acoes") + "?q=2804:ABCD"), "Ação do IPv6")

    def test_caractere_nulo_recusado_antes_do_banco(self):
        """O PostgreSQL recusa NUL num texto (erro 500); o sistema responde 400 antes de consultar."""
        self.entrar(self.ori)
        self.assertEqual(self.client.get(reverse("registro_acoes") + "?q=a%00b").status_code, 400)
        self.client.logout()
        r = self.client.post(reverse("login"), {"auth-username": "a\x00b@x.br", "username": "a\x00b@x.br",
                                                "password": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_historico_da_agenda_deixa_os_sem_data_no_fim(self):
        """O PostgreSQL põe os vazios (NULL) primeiro na ordem decrescente; o sistema sempre os mostrou no fim."""
        A = Agendamento
        com_data = A.objects.create(orientador=self.ori, solicitante=self.ori, status=A.Status.REALIZADO,
                                    assunto="Com data", data_hora=timezone.now() - timedelta(days=3))
        sem_data = A.objects.create(orientador=self.ori, solicitante=self.ori, status=A.Status.CANCELADO,
                                    assunto="Sem data")
        self.entrar(self.ori)
        historico = list(self.client.get(reverse("agendamentos")).context["historico"])
        self.assertEqual(historico, [com_data, sem_data])


class AvisosVerificarParaPostgresTests(SimpleTestCase):
    """verificar_para_postgres avisa do que o PostgreSQL vai tratar diferente, mostrando só ids."""

    def _banco(self, pasta):
        caminho = Path(pasta) / "pequeno.sqlite3"
        con = sqlite3.connect(caminho)
        con.executescript("""
            CREATE TABLE core_usuario (id INTEGER PRIMARY KEY, username TEXT, email TEXT, is_active INTEGER,
                                       nome_completo TEXT, papel TEXT);
            CREATE TABLE core_localestagio (id INTEGER PRIMARY KEY, nome TEXT, cnpj TEXT);
            CREATE TABLE core_curso (id INTEGER PRIMARY KEY, nome TEXT);
        """)
        con.executemany("INSERT INTO core_usuario VALUES (?, ?, ?, ?, ?, ?)", [
            (1, "ana.lima", "ana@exemplo.br", 1, "Ana Lima", "ESTAGIARIO"),
            (2, "Ana.Lima", "ANA@exemplo.br", 1, "Ana Souza", "ESTAGIARIO"),
            (3, "jose.reis", "jose@exemplo.br", 1, "JOSÉ REIS", "ESTAGIARIO"),
            (4, "jose.reis2", "jose2@exemplo.br", 1, "JOSé REIS", "ESTAGIARIO"),
            (5, "bia.melo", "bia@exemplo.br", 0, "Bia Melo", "SUPERVISOR"),
            (6, "bia.melo2", "BIA@exemplo.br", 0, "Bia Melo", "SUPERVISOR"),  # inativas: e-mail não conta
        ])
        con.executemany("INSERT INTO core_localestagio VALUES (?, ?, ?)", [
            (1, "Secretaria de Saúde", "07.954.571/0001-04"), (2, "SECRETARIA DE SAUDE", "07954571000104"),
            (3, "Secretaria de Saúde", ""),
        ])
        con.executemany("INSERT INTO core_curso VALUES (?, ?)", [(1, "Informática"), (2, "INFORMATICA"), (3, "Redes")])
        con.commit()
        con.close()
        return caminho

    def test_avisos_so_com_ids(self):
        from .migracao_banco import avisos_sqlite

        with tempfile.TemporaryDirectory() as pasta:
            avisos = {(a["tabela"], a["campo"]): a["grupos"] for a in avisos_sqlite(self._banco(pasta))}
            self.assertEqual(avisos[("core_usuario", "username")], [[1, 2]])
            self.assertEqual(avisos[("core_usuario", "email")], [[1, 2]])
            self.assertEqual(avisos[("core_usuario", "nome_completo")], [[3, 4]])  # só o “É/é”: no SQLite eram diferentes
            self.assertEqual(avisos[("core_localestagio", "nome")], [[1, 2]])
            self.assertEqual(avisos[("core_curso", "nome")], [[1, 2]])
            saida = StringIO()
            with self.assertRaises(CommandError):  # o banco de exemplo não tem as outras tabelas
                call_command("verificar_para_postgres", "--banco", str(Path(pasta) / "pequeno.sqlite3"), stdout=saida)
            texto = saida.getvalue()
            self.assertIn("Avisos (não impedem a cópia", texto)
            self.assertIn("core_usuario.email", texto)
            for dado in ("ana@", "Ana Lima", "Saúde", "Informática"):
                self.assertNotIn(dado, texto)
