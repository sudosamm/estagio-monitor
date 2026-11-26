"""Backup do volume de dados (core/backup.py): criptografia, assinatura S3, retenção 7/4/6 e restauração."""
import datetime as dt
import json
import os
import shutil
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core import backup


class CriptografiaTests(SimpleTestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.chave = backup.carregar_chave(backup.gerar_chave())

    def _ida_e_volta(self, conteudo, chave_volta=None):
        (self.pasta / "a").write_bytes(conteudo)
        backup.cifrar(self.pasta / "a", self.pasta / "b", self.chave)
        backup.decifrar(self.pasta / "b", self.pasta / "c", chave_volta or self.chave)
        return (self.pasta / "c").read_bytes()

    def test_ida_e_volta_varios_tamanhos(self):
        for tamanho in (0, 1, backup.TAM_BLOCO - 1, backup.TAM_BLOCO, backup.TAM_BLOCO * 2 + 7):
            dados = os.urandom(tamanho)
            self.assertEqual(self._ida_e_volta(dados), dados, tamanho)

    def test_texto_cifrado_nao_contem_o_original(self):
        (self.pasta / "a").write_bytes(b"CPF 123.456.789-00 " * 100)
        backup.cifrar(self.pasta / "a", self.pasta / "b", self.chave)
        self.assertNotIn(b"123.456.789-00", (self.pasta / "b").read_bytes())

    def test_chave_errada_nao_abre(self):
        with self.assertRaisesMessage(backup.ErroBackup, "chave errada"):
            self._ida_e_volta(b"x" * 100, chave_volta=backup.carregar_chave(backup.gerar_chave()))

    def test_arquivo_cortado_nao_abre(self):
        (self.pasta / "a").write_bytes(os.urandom(backup.TAM_BLOCO + 10))
        backup.cifrar(self.pasta / "a", self.pasta / "b", self.chave)
        dados = (self.pasta / "b").read_bytes()
        primeiro_bloco = len(backup.MAGICO) + 32 + 5 + backup.TAM_BLOCO + 16
        (self.pasta / "b").write_bytes(dados[:primeiro_bloco])  # só o primeiro bloco, sem o último
        with self.assertRaises(backup.ErroBackup):
            backup.decifrar(self.pasta / "b", self.pasta / "c", self.chave)

    def test_byte_alterado_nao_abre(self):
        (self.pasta / "a").write_bytes(b"conteudo" * 50)
        backup.cifrar(self.pasta / "a", self.pasta / "b", self.chave)
        dados = bytearray((self.pasta / "b").read_bytes())
        dados[-3] ^= 1
        (self.pasta / "b").write_bytes(bytes(dados))
        with self.assertRaises(backup.ErroBackup):
            backup.decifrar(self.pasta / "b", self.pasta / "c", self.chave)

    def test_chave_invalida(self):
        for ruim in ("", "curta", "%%%"):
            with self.assertRaises(backup.ErroBackup):
                backup.carregar_chave(ruim)


class AssinaturaS3Tests(SimpleTestCase):
    """Vetores do exemplo oficial da AWS (Signature Version 4, “GET Object” e “GET Bucket (List Objects)”)."""

    ID = "AKIAIOSFODNN7EXAMPLE"
    SEGREDO = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    AGORA = dt.datetime(2013, 5, 24, tzinfo=dt.timezone.utc)

    def test_get_object(self):
        cab = backup.assinar("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"},
                             backup.VAZIO_SHA256, self.ID, self.SEGREDO, "us-east-1", self.AGORA)
        self.assertIn("SignedHeaders=host;range;x-amz-content-sha256;x-amz-date", cab["authorization"])
        self.assertTrue(cab["authorization"].endswith(
            "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"))

    def test_listar(self):
        cab = backup.assinar("GET", "https://examplebucket.s3.amazonaws.com/?max-keys=2&prefix=J", {},
                             backup.VAZIO_SHA256, self.ID, self.SEGREDO, "us-east-1", self.AGORA)
        self.assertTrue(cab["authorization"].endswith(
            "Signature=34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"))

    def test_sem_configuracao(self):
        with self.assertRaises(backup.ErroBackup):
            backup.ArmazenamentoS3("", "", "", "")


def _nome(ano, mes, dia, hora=3):
    return f"p/{dt.datetime(ano, mes, dia, hora).strftime(backup.NOME_RE)}{backup.SUFIXO}"


class RetencaoTests(SimpleTestCase):
    def test_sete_quatro_seis(self):
        inicio = dt.date(2026, 1, 1)
        chaves = [_nome(d.year, d.month, d.day) for d in (inicio + dt.timedelta(n) for n in range(365))]
        apagar = set(backup.escolher_para_apagar(chaves))
        manter = sorted(set(chaves) - apagar)
        self.assertLessEqual(len(manter), 7 + 4 + 6)
        datas = [backup.data_do_nome(c).date() for c in manter]
        ultimo = dt.date(2026, 12, 31)
        for n in range(7):  # últimos 7 dias, todos
            self.assertIn(ultimo - dt.timedelta(n), datas)
        self.assertGreaterEqual(len({(d.year, d.month) for d in datas}), 6)  # 6 meses diferentes
        self.assertGreaterEqual(len({d.isocalendar()[:2] for d in datas}), 4)

    def test_mais_recente_fica_e_nome_estranho_nunca_sai(self):
        chaves = [_nome(2026, 1, 1, h) for h in range(5)] + ["p/outro-arquivo.txt"]
        apagar = backup.escolher_para_apagar(chaves, diarios=1, semanais=0, mensais=0)
        self.assertNotIn(_nome(2026, 1, 1, 4), apagar)
        self.assertNotIn("p/outro-arquivo.txt", apagar)
        self.assertEqual(len(apagar), 4)

    def test_poucos_backups_nada_sai(self):
        chaves = [_nome(2026, 3, d) for d in (1, 2, 3)]
        self.assertEqual(backup.escolher_para_apagar(chaves), [])


class BackupCompletoTests(SimpleTestCase):
    """Backup e restauração de ponta a ponta, com um /data falso e o armazenamento numa pasta."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.dados = self.raiz / "data"
        (self.dados / "anexos" / "atestados").mkdir(parents=True)
        (self.dados / "anexos" / "atestados" / "x.pdf").write_bytes(b"%PDF ficticio")
        (self.dados / "anexos" / "fotos.png").write_bytes(b"\x89PNG ficticio")
        (self.dados / "vapid_privada.pem").write_text("chave ficticia")
        con = sqlite3.connect(self.dados / "db.sqlite3")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, nome TEXT)")
        con.executemany("INSERT INTO t (nome) VALUES (?)", [("Pessoa Ficticia %d" % i,) for i in range(50)])
        con.commit()
        self.con = con  # fica aberta (WAL com dados ainda não copiados para o arquivo principal)
        self.addCleanup(con.close)
        self.chave = backup.gerar_chave()
        self.cfg = override_settings(
            DATA_DIR=self.dados, MEDIA_ROOT=self.dados / "anexos", VAPID_ARQUIVO=self.dados / "vapid_privada.pem",
            BACKUP_SQLITE=str(self.dados / "db.sqlite3"),
            BACKUP_CHAVE=self.chave, BACKUP_PASTA=str(self.raiz / "remoto"), BACKUP_PREFIXO="volume",
            BACKUP_TRABALHO=str(self.raiz / "trabalho"))
        self.cfg.enable()
        self.addCleanup(self.cfg.disable)

    def test_backup_e_restauracao(self):
        r = backup.fazer_backup()
        self.assertEqual(r["linhas"], 50)
        self.assertEqual(r["anexos"], 2)
        guardados = list((self.raiz / "remoto" / "volume").iterdir())
        self.assertEqual(len(guardados), 1)
        self.assertNotIn(b"Pessoa Ficticia", guardados[0].read_bytes())
        self.assertEqual(list((self.raiz / "trabalho").iterdir()), [])  # nada sobra na pasta de trabalho

        teste = backup.restaurar()
        self.assertTrue(teste["ok"], teste["problemas"])

        destino = self.raiz / "restaurado"
        r2 = backup.restaurar(destino=destino)
        self.assertTrue(r2["ok"])
        self.assertEqual((destino / "anexos" / "atestados" / "x.pdf").read_bytes(), b"%PDF ficticio")
        con = sqlite3.connect(destino / "db.sqlite3")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM t").fetchone()[0], 50)
        con.close()
        manifesto = json.loads((destino / "manifesto.json").read_text())
        self.assertNotIn("Pessoa", json.dumps(manifesto))
        self.assertNotIn("x.pdf", json.dumps(manifesto))

    def test_restauracao_detecta_diferenca(self):
        backup.fazer_backup()
        destino = self.raiz / "r"
        backup.restaurar(destino=destino)
        (destino / "anexos" / "a-mais.txt").write_text("x")
        ok, problemas, _ = backup.conferir_extraido(destino)
        self.assertFalse(ok)
        self.assertTrue(any("anexos" in p for p in problemas))

    def test_nao_restaura_em_pasta_cheia_nem_em_data_dir(self):
        backup.fazer_backup()
        with self.assertRaises(backup.ErroBackup):
            backup.restaurar(destino=self.dados)

    def test_retencao_apaga_antigos_depois_de_enviar(self):
        remoto = self.raiz / "remoto" / "volume"
        remoto.mkdir(parents=True)
        for d in range(1, 21):
            (remoto / _nome(2025, 1, d).split("/")[1]).write_bytes(b"velho")
        r = backup.fazer_backup(agora=dt.datetime(2025, 1, 25, 3, tzinfo=dt.timezone.utc))
        self.assertTrue(r["apagados"])
        restantes = {p.name for p in remoto.iterdir()}
        self.assertIn(r["chave"].split("/")[1], restantes)
        self.assertLessEqual(len(restantes), 7 + 4 + 6)

    def test_comando(self):
        saida = StringIO()
        call_command("backup_dados", stdout=saida)
        self.assertIn("Backup enviado", saida.getvalue())
        saida = StringIO()
        call_command("backup_dados", "--testar-restauracao", stdout=saida)
        self.assertIn("Restauração conferida", saida.getvalue())
        saida = StringIO()
        call_command("backup_dados", "--listar", stdout=saida)
        self.assertIn("1 objeto(s)", saida.getvalue())

    def test_comando_sem_chave_falha_com_mensagem(self):
        with override_settings(BACKUP_CHAVE=""), self.assertRaisesMessage(CommandError, "BACKUP_CHAVE"):
            call_command("backup_dados", stdout=StringIO())

    def test_gerar_chave(self):
        saida = StringIO()
        call_command("backup_dados", "--gerar-chave", stdout=saida)
        self.assertEqual(len(backup.carregar_chave(saida.getvalue())), 32)
