"""Troca de banco: leitura da DATABASE_URL, verificação do SQLite e comparação entre bancos (core/migracao_banco.py).

A comparação é testada com dois arquivos SQLite e o mesmo caminho do procedimento real (migrate, dumpdata,
loaddata). Com DATABASE_URL apontando para um PostgreSQL, a suíte inteira roda nele (ver docs/operacao).
"""
import shutil
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from core.migracao_banco import verificar_sqlite
from monitor.banco import config_da_url


class SerializacaoPrecisaTests(SimpleTestCase):
    def test_microssegundos_preservados(self):
        import datetime as dt
        import json

        from core.serializacao_precisa import CodificadorPreciso

        agora = dt.datetime(2026, 11, 25, 12, 30, 15, 123456, tzinfo=dt.timezone.utc)
        texto = json.dumps({"q": agora, "h": dt.time(7, 1, 2, 345678)}, cls=CodificadorPreciso)
        self.assertIn("12:30:15.123456Z", texto)
        self.assertIn("07:01:02.345678", texto)


class DatabaseUrlTests(SimpleTestCase):
    def test_postgres(self):
        cfg = config_da_url("postgres://app:s%40nha@banco.interno:5433/estagio?sslmode=disable")
        self.assertEqual(cfg["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual((cfg["USER"], cfg["PASSWORD"], cfg["HOST"], cfg["PORT"], cfg["NAME"]),
                         ("app", "s@nha", "banco.interno", "5433", "estagio"))
        self.assertEqual(cfg["OPTIONS"], {"sslmode": "disable"})
        self.assertTrue(cfg["CONN_HEALTH_CHECKS"])
        self.assertEqual(cfg["CONN_MAX_AGE"], 60)

    def test_sqlite(self):
        cfg = config_da_url("sqlite:////data/migracao/db.sqlite3")
        self.assertEqual(cfg["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(cfg["NAME"], "/data/migracao/db.sqlite3")
        with self.assertRaises(ValueError):
            config_da_url("sqlite://relativo/db.sqlite3")

    def test_invalidas(self):
        for url in ("mysql://a@b/c", "postgres://a@b/", ""):
            with self.assertRaises(ValueError):
                config_da_url(url)


POPULAR = """
from datetime import date
from core.models import Curso, Estagio, LocalEstagio, Usuario
curso = Curso.objects.create(nome="Técnico em Demonstração")
o = Usuario.objects.create(username="ori.demo", nome_completo="Orientadora Fictícia", papel="ORIENTADOR")
for i in range(5):  # ids com buraco, como na produção
    Usuario.objects.create(username=f"apagar.{i}", nome_completo="Apagar", papel="ESTAGIARIO").delete()
e = Usuario.objects.create(username="est.demo", nome_completo="Estudante Fictício", papel="ESTAGIARIO")
local = LocalEstagio.objects.create(nome="Concedente Fictícia", cnpj="00.000.000/0001-00")
Estagio.objects.create(estagiario=e, orientador=o, curso=curso, local=local, data_inicio=date(2026, 8, 1))
"""


class CopiaEntreBancosTests(SimpleTestCase):
    """Do SQLite “de produção” (fictício) para outro banco, com os mesmos comandos do procedimento, cada um num
    processo próprio (como no servidor)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pasta = Path(tempfile.mkdtemp())
        cls.origem = cls.pasta / "origem.sqlite3"
        cls._manage("migrate", url=cls._url(cls.origem))
        cls._manage("shell", "-c", POPULAR, url=cls._url(cls.origem))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.pasta, True)
        super().tearDownClass()

    @staticmethod
    def _url(caminho):
        return f"sqlite:///{caminho}"

    @classmethod
    def _manage(cls, *args, url, checar=True):
        import os
        import subprocess
        import sys

        from django.conf import settings

        env = dict(os.environ, DATABASE_URL=url, DATA_DIR=str(cls.pasta / "data"), SECRET_KEY="teste-copia",
                   RESUMO_AUTOMATICO="0", PUSH_ATIVO="0", EMAIL_HOST="")
        r = subprocess.run([sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), *args], env=env,
                           capture_output=True, text=True, timeout=300)
        if checar and r.returncode != 0:
            raise AssertionError(f"manage.py {args[0]} falhou:\n{r.stdout}\n{r.stderr}")
        return r

    def test_verificacao_limpa_e_com_problemas(self):
        problemas, contagens = verificar_sqlite(self.origem)
        self.assertEqual(problemas, [])
        self.assertEqual(contagens["core_curso"], 1)
        copia = self.pasta / "ruim.sqlite3"
        shutil.copyfile(self.origem, copia)
        con = sqlite3.connect(copia)
        con.execute("UPDATE core_curso SET nome = ?", ("x" * 300,))
        con.execute("UPDATE core_localestagio SET cidade = ?", ("Cida\x00de",))
        con.execute("INSERT INTO core_registroacao (quando, quem, tipo, descricao, alvo, caminho, ip, aparelho) "
                    "VALUES ('2026-01-01 00:00:00', '', 't', 'd', '', '', 'nao-e-ip', '')")
        con.commit()
        con.close()
        problemas, _ = verificar_sqlite(copia)
        tipos = {(p["tabela"], p["campo"]): p["problema"] for p in problemas}
        self.assertIn("limite do campo é 120", tipos[("core_curso", "nome")])
        self.assertIn("NUL", tipos[("core_localestagio", "cidade")])
        self.assertIn("IP", tipos[("core_registroacao", "ip")])
        for p in problemas:  # o relatório não traz o conteúdo
            self.assertNotIn("xxxx", str(p))
        with self.assertRaises(CommandError):
            call_command("verificar_para_postgres", "--banco", str(copia), stdout=StringIO())
        saida = StringIO()
        call_command("verificar_para_postgres", "--banco", str(self.origem), stdout=saida)
        self.assertIn("Nenhum problema", saida.getvalue())

    def test_dumpdata_loaddata_e_comparacao(self):
        destino = self.pasta / "destino.sqlite3"
        dump = self.pasta / "dados.jsonlp.gz"
        self._manage("dumpdata", "--all", "--natural-foreign", "--exclude", "contenttypes", "--exclude", "auth.permission",
                     "--format", "jsonlp", "-o", str(dump), url=self._url(self.origem))
        self._manage("migrate", url=self._url(destino))
        self._manage("loaddata", str(dump), url=self._url(destino))
        r = self._manage("comparar_bancos", "--origem", self._url(self.origem), url=self._url(destino))
        self.assertIn("iguais", r.stdout)
        a, b = sqlite3.connect(self.origem), sqlite3.connect(destino)
        ids = "SELECT id FROM core_usuario ORDER BY id"
        # os ids das contas são preservados (sessões, links e códigos dependem deles)
        self.assertEqual(a.execute(ids).fetchall(), b.execute(ids).fetchall())
        self.assertGreater(b.execute(ids).fetchall()[-1][0], 6)  # o buraco nos ids continua lá
        b.execute("UPDATE core_usuario SET telefone = '(85) 90000-0000' WHERE username = 'est.demo'")
        b.commit()
        a.close()
        b.close()
        r = self._manage("comparar_bancos", "--origem", self._url(self.origem), url=self._url(destino), checar=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("core_usuario", r.stdout)
        self.assertNotIn("90000", r.stdout + r.stderr)
