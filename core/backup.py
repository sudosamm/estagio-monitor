"""Backup do volume de dados (/data) para fora do servidor, num armazenamento compatível com S3 (Cloudflare R2).

O que entra no pacote (um .tar.gz cifrado por backup):
- uma cópia consistente do banco SQLite (API de backup do próprio SQLite, sem parar a aplicação), quando o sistema
  usa SQLite. Com PostgreSQL (DATABASE_URL), o banco fica de fora: ele tem o backup agendado do Coolify;
- a pasta de anexos (``MEDIA_ROOT``) e a chave VAPID (notificações no celular);
- um ``manifesto.json`` com contagens (linhas por tabela, quantidade e tamanho dos arquivos) e o resultado do
  ``PRAGMA integrity_check``. O manifesto não tem dados pessoais: nem nomes de arquivos, nem conteúdo de linhas.

Criptografia: AES-256-GCM em blocos, com uma chave derivada (HKDF) por arquivo a partir de ``BACKUP_CHAVE``. A chave
fica só nas variáveis de ambiente (e guardada por você num lugar seguro, fora do servidor): sem ela, o backup não
abre. Cada bloco é autenticado com o número dele e a marca de último bloco, então um arquivo cortado ou trocado de
ordem não abre.

Retenção (ver ``escolher_para_apagar``): o mais recente de cada um dos últimos 7 dias, 4 semanas e 6 meses.

O cliente S3 é mínimo (assinatura AWS Signature V4 com ``requests``), sem dependência nova. Ele só faz o que o
backup precisa: enviar, baixar, listar e apagar objetos de um bucket.
"""
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import logging
import os
import shutil
import sqlite3
import struct
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

from django.conf import settings

log = logging.getLogger("core.backup")

MAGICO = b"EMBK1\n"  # Estágio Monitor BacKup, versão 1 do formato
TAM_BLOCO = 4 * 1024 * 1024
NOME_RE = "dados-%Y%m%d-%H%M%S"
SUFIXO = ".tar.gz.enc"


class ErroBackup(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------
# Criptografia em blocos
# ---------------------------------------------------------------------------------------------------------------
def carregar_chave(texto=None):
    """``BACKUP_CHAVE``: 32 bytes em base64 (gere com ``python manage.py backup_dados --gerar-chave``)."""
    texto = (texto if texto is not None else getattr(settings, "BACKUP_CHAVE", "")).strip()
    if not texto:
        raise ErroBackup("BACKUP_CHAVE não definida. Gere uma com  python manage.py backup_dados --gerar-chave")
    try:
        chave = base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
    except (ValueError, TypeError) as exc:
        raise ErroBackup("BACKUP_CHAVE inválida (esperado: base64 de 32 bytes).") from exc
    if len(chave) != 32:
        raise ErroBackup("BACKUP_CHAVE inválida: precisa ter 32 bytes (256 bits).")
    return chave


def gerar_chave():
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


def _chave_do_arquivo(chave, sal):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=sal, info=b"estagio-monitor-backup").derive(chave)


def _nonce(n):
    return b"\0\0\0\0" + struct.pack(">Q", n)


def _aad(cabecalho, n, ultimo):
    return cabecalho + struct.pack(">QB", n, 1 if ultimo else 0)


def cifrar(origem, destino, chave):
    """Cifra o arquivo ``origem`` em ``destino`` (caminhos). Formato: MAGICO + sal(32) + blocos
    [tamanho(4) + último(1) + texto cifrado com etiqueta]."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    sal = os.urandom(32)
    cabecalho = MAGICO + sal
    aes = AESGCM(_chave_do_arquivo(chave, sal))
    with open(origem, "rb") as fe, open(destino, "wb") as fs:
        fs.write(cabecalho)
        n = 0
        atual = fe.read(TAM_BLOCO)
        while True:
            proximo = fe.read(TAM_BLOCO)
            ultimo = not proximo
            cifrado = aes.encrypt(_nonce(n), atual, _aad(cabecalho, n, ultimo))
            fs.write(struct.pack(">IB", len(cifrado), 1 if ultimo else 0))
            fs.write(cifrado)
            if ultimo:
                break
            atual, n = proximo, n + 1


def decifrar(origem, destino, chave):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with open(origem, "rb") as fe, open(destino, "wb") as fs:
        cabecalho = fe.read(len(MAGICO) + 32)
        if not cabecalho.startswith(MAGICO) or len(cabecalho) != len(MAGICO) + 32:
            raise ErroBackup("O arquivo não é um backup do Estágio Monitor (ou está corrompido).")
        aes = AESGCM(_chave_do_arquivo(chave, cabecalho[len(MAGICO):]))
        n = 0
        while True:
            topo = fe.read(5)
            if len(topo) != 5:
                raise ErroBackup("Backup incompleto: o arquivo termina antes do último bloco.")
            tamanho, ultimo = struct.unpack(">IB", topo)
            if tamanho > TAM_BLOCO + 16:
                raise ErroBackup("Backup corrompido (bloco maior que o esperado).")
            cifrado = fe.read(tamanho)
            try:
                fs.write(aes.decrypt(_nonce(n), cifrado, _aad(cabecalho, n, bool(ultimo))))
            except InvalidTag as exc:
                raise ErroBackup("Não foi possível abrir o backup: chave errada ou arquivo alterado.") from exc
            if ultimo:
                if fe.read(1):
                    raise ErroBackup("Backup corrompido (dados depois do último bloco).")
                return
            n += 1


# ---------------------------------------------------------------------------------------------------------------
# Cliente S3 mínimo (AWS Signature V4)
# ---------------------------------------------------------------------------------------------------------------
def _hmac(chave, texto):
    return hmac.new(chave, texto.encode(), hashlib.sha256).digest()


def _sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for parte in iter(lambda: f.read(1024 * 1024), b""):
            h.update(parte)
    return h.hexdigest()


VAZIO_SHA256 = hashlib.sha256(b"").hexdigest()


def assinar(metodo, url, cabecalhos, payload_sha256, chave_id, segredo, regiao, agora, servico="s3"):
    """Devolve os cabeçalhos assinados (Authorization, x-amz-date, x-amz-content-sha256). Segue a especificação da
    AWS (Signature Version 4); o R2 usa a região ``auto``."""
    partes = urlsplit(url)
    data_hora = agora.strftime("%Y%m%dT%H%M%SZ")
    data = agora.strftime("%Y%m%d")
    cab = {k.lower(): str(v).strip() for k, v in cabecalhos.items()}
    cab["host"] = partes.netloc
    cab["x-amz-date"] = data_hora
    cab["x-amz-content-sha256"] = payload_sha256
    nomes = sorted(cab)
    canon_cab = "".join(f"{k}:{cab[k]}\n" for k in nomes)
    assinados = ";".join(nomes)
    pares = []
    for item in filter(None, partes.query.split("&")):
        k, _, v = item.partition("=")
        pares.append((quote(_desfazer(k), safe="-_.~"), quote(_desfazer(v), safe="-_.~")))
    canon_query = "&".join(f"{k}={v}" for k, v in sorted(pares))
    canon_path = quote(_desfazer(partes.path or "/"), safe="/-_.~")
    pedido = "\n".join([metodo, canon_path, canon_query, canon_cab, assinados, payload_sha256])
    escopo = f"{data}/{regiao}/{servico}/aws4_request"
    a_assinar = "\n".join(["AWS4-HMAC-SHA256", data_hora, escopo, hashlib.sha256(pedido.encode()).hexdigest()])
    k = _hmac(("AWS4" + segredo).encode(), data)
    k = _hmac(k, regiao)
    k = _hmac(k, servico)
    k = _hmac(k, "aws4_request")
    assinatura = hmac.new(k, a_assinar.encode(), hashlib.sha256).hexdigest()
    saida = {k2: v for k2, v in cab.items() if k2 != "host"}
    saida["authorization"] = (f"AWS4-HMAC-SHA256 Credential={chave_id}/{escopo}, SignedHeaders={assinados}, "
                              f"Signature={assinatura}")
    return saida


def _desfazer(texto):
    from urllib.parse import unquote

    return unquote(texto)


@dataclass
class Objeto:
    chave: str
    tamanho: int


class ArmazenamentoS3:
    """Bucket S3/R2 com endereço no caminho (``https://<conta>.r2.cloudflarestorage.com/<bucket>/<chave>``)."""

    def __init__(self, endpoint, bucket, chave_id, segredo, regiao="auto", timeout=120):
        if not (endpoint and bucket and chave_id and segredo):
            raise ErroBackup("Configure BACKUP_S3_ENDPOINT, BACKUP_S3_BUCKET, BACKUP_S3_CHAVE_ID e BACKUP_S3_SEGREDO.")
        self.base = endpoint.rstrip("/") + "/" + bucket
        self.chave_id, self.segredo, self.regiao, self.timeout = chave_id, segredo, regiao or "auto", timeout

    @classmethod
    def das_configuracoes(cls):
        return cls(settings.BACKUP_S3_ENDPOINT, settings.BACKUP_S3_BUCKET, settings.BACKUP_S3_CHAVE_ID,
                   settings.BACKUP_S3_SEGREDO, settings.BACKUP_S3_REGIAO)

    def _pedir(self, metodo, chave="", query="", corpo=None, sha=VAZIO_SHA256, cabecalhos=None, stream=False):
        import requests

        url = self.base + ("/" + quote(chave, safe="/-_.~") if chave else "") + (f"?{query}" if query else "")
        cab = assinar(metodo, url, cabecalhos or {}, sha, self.chave_id, self.segredo, self.regiao,
                      dt.datetime.now(dt.timezone.utc))
        resp = requests.request(metodo, url, headers=cab, data=corpo, timeout=self.timeout, stream=stream)
        if resp.status_code >= 300:
            raise ErroBackup(f"Armazenamento respondeu {resp.status_code} em {metodo} {chave or '(bucket)'}: "
                             f"{resp.text[:300]}")
        return resp

    def enviar(self, caminho, chave):
        tamanho = os.path.getsize(caminho)
        with open(caminho, "rb") as f:
            self._pedir("PUT", chave, corpo=f, sha=_sha256_arquivo(caminho),
                        cabecalhos={"content-length": str(tamanho), "content-type": "application/octet-stream"})

    def baixar(self, chave, caminho):
        resp = self._pedir("GET", chave, stream=True)
        with open(caminho, "wb") as f:
            for parte in resp.iter_content(1024 * 1024):
                f.write(parte)

    def listar(self, prefixo):
        objetos, token = [], None
        while True:
            query = "list-type=2&prefix=" + quote(prefixo, safe="")
            if token:
                query += "&continuation-token=" + quote(token, safe="")
            raiz = ElementTree.fromstring(self._pedir("GET", query=query).content)
            ns = raiz.tag.split("}")[0] + "}" if raiz.tag.startswith("{") else ""
            for c in raiz.findall(f"{ns}Contents"):
                objetos.append(Objeto(c.findtext(f"{ns}Key"), int(c.findtext(f"{ns}Size") or 0)))
            if raiz.findtext(f"{ns}IsTruncated") != "true":
                return objetos
            token = raiz.findtext(f"{ns}NextContinuationToken")

    def apagar(self, chave):
        self._pedir("DELETE", chave)


class ArmazenamentoPasta:
    """Mesma interface, numa pasta local. Serve para os testes e para um backup extra num disco montado."""

    def __init__(self, pasta):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)

    def enviar(self, caminho, chave):
        destino = self.pasta / chave
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(caminho, destino)

    def baixar(self, chave, caminho):
        shutil.copyfile(self.pasta / chave, caminho)

    def listar(self, prefixo):
        return [Objeto(str(p.relative_to(self.pasta)).replace(os.sep, "/"), p.stat().st_size)
                for p in sorted(self.pasta.rglob("*")) if p.is_file()
                and str(p.relative_to(self.pasta)).replace(os.sep, "/").startswith(prefixo)]

    def apagar(self, chave):
        (self.pasta / chave).unlink(missing_ok=True)


def armazenamento_padrao():
    pasta = getattr(settings, "BACKUP_PASTA", "")
    return ArmazenamentoPasta(pasta) if pasta else ArmazenamentoS3.das_configuracoes()


# ---------------------------------------------------------------------------------------------------------------
# Retenção 7/4/6
# ---------------------------------------------------------------------------------------------------------------
def data_do_nome(chave):
    nome = chave.rsplit("/", 1)[-1]
    if not nome.endswith(SUFIXO):
        return None
    try:
        return dt.datetime.strptime(nome[: -len(SUFIXO)], NOME_RE)
    except ValueError:
        return None


def escolher_para_apagar(chaves, diarios=7, semanais=4, mensais=6):
    """Fica o backup mais recente de cada um dos últimos ``diarios`` dias, ``semanais`` semanas (ISO) e ``mensais``
    meses que têm backup. O mais recente de todos nunca sai. Chaves que não seguem o padrão do nome nunca saem."""
    datadas = sorted(((data_do_nome(c), c) for c in chaves if data_do_nome(c)), reverse=True)
    manter = set()
    if datadas:
        manter.add(datadas[0][1])
    for limite, grupo in ((diarios, lambda d: d.date()), (semanais, lambda d: d.isocalendar()[:2]),
                          (mensais, lambda d: (d.year, d.month))):
        vistos = []
        for quando, chave in datadas:
            g = grupo(quando)
            if g not in vistos:
                if len(vistos) >= limite:
                    break
                vistos.append(g)
                manter.add(chave)
    return [c for _, c in datadas if c not in manter]


# ---------------------------------------------------------------------------------------------------------------
# Montagem e conferência do pacote
# ---------------------------------------------------------------------------------------------------------------
def _usa_sqlite():
    return bool(getattr(settings, "BACKUP_SQLITE", "")) or settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def _caminho_sqlite():
    return Path(getattr(settings, "BACKUP_SQLITE", "") or settings.DATABASES["default"]["NAME"])


def copiar_sqlite(origem, destino):
    """Cópia consistente com a aplicação no ar (API de backup do SQLite; respeita o WAL)."""
    fonte = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    alvo = sqlite3.connect(destino)
    try:
        fonte.backup(alvo)
    finally:
        alvo.close()
        fonte.close()


def contar_sqlite(caminho):
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        integridade = con.execute("PRAGMA integrity_check").fetchone()[0]
        tabelas = [t for (t,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        contagens = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tabelas}
    finally:
        con.close()
    return integridade, contagens


def _contar_arquivos(pasta):
    n = total = 0
    if pasta.exists():
        for p in pasta.rglob("*"):
            if p.is_file():
                n += 1
                total += p.stat().st_size
    return n, total


def montar_pacote(trabalho, agora):
    """Cria ``<trabalho>/pacote.tar.gz`` e devolve (caminho, manifesto)."""
    anexos = Path(settings.MEDIA_ROOT)
    vapid = Path(settings.VAPID_ARQUIVO)
    manifesto = {"formato": 1, "criado_em": agora.isoformat(), "banco": None, "arquivos": {}}
    banco_copia = None
    if _usa_sqlite():
        banco = _caminho_sqlite()
        if banco.exists():
            banco_copia = Path(trabalho) / "db.sqlite3"
            copiar_sqlite(banco, banco_copia)
            integridade, contagens = contar_sqlite(banco_copia)
            if integridade != "ok":
                raise ErroBackup(f"A cópia do banco não passou no integrity_check: {integridade[:200]}")
            manifesto["banco"] = {"tipo": "sqlite", "integridade": integridade, "tabelas": contagens}
    else:
        manifesto["banco"] = {"tipo": "externo", "observacao": "PostgreSQL: backup próprio no Coolify"}
    n, total = _contar_arquivos(anexos)
    manifesto["arquivos"] = {"anexos": n, "bytes": total, "vapid": vapid.exists()}
    caminho = Path(trabalho) / "pacote.tar.gz"
    with tarfile.open(caminho, "w:gz", compresslevel=6) as tar:
        dados = json.dumps(manifesto, ensure_ascii=False, indent=1).encode()
        info = tarfile.TarInfo("manifesto.json")
        info.size, info.mtime = len(dados), int(agora.timestamp())
        tar.addfile(info, io.BytesIO(dados))
        if banco_copia:
            tar.add(banco_copia, arcname="db.sqlite3")
        if anexos.exists():
            tar.add(anexos, arcname="anexos")
        if vapid.exists():
            tar.add(vapid, arcname="vapid_privada.pem")
    return caminho, manifesto


def _extrair(tar_caminho, destino):
    with tarfile.open(tar_caminho, "r:gz") as tar:
        tar.extractall(destino, filter="data")  # recusa caminhos absolutos, "..", links para fora


def conferir_extraido(pasta):
    """Confere um backup extraído contra o próprio manifesto. Devolve (ok, lista de problemas, manifesto)."""
    pasta = Path(pasta)
    problemas = []
    try:
        manifesto = json.loads((pasta / "manifesto.json").read_text())
    except (OSError, ValueError):
        return False, ["manifesto.json ausente ou ilegível"], None
    banco = manifesto.get("banco") or {}
    if banco.get("tipo") == "sqlite":
        if not (pasta / "db.sqlite3").exists():
            problemas.append("o banco não está no pacote")
        else:
            integridade, contagens = contar_sqlite(pasta / "db.sqlite3")
            if integridade != "ok":
                problemas.append(f"integrity_check: {integridade[:200]}")
            esperadas = banco.get("tabelas") or {}
            for tabela in sorted(set(esperadas) | set(contagens)):
                if esperadas.get(tabela) != contagens.get(tabela):
                    problemas.append(f"tabela {tabela}: esperado {esperadas.get(tabela)}, restaurado {contagens.get(tabela)}")
    n, total = _contar_arquivos(pasta / "anexos")
    arq = manifesto.get("arquivos") or {}
    if (n, total) != (arq.get("anexos", 0), arq.get("bytes", 0)):
        problemas.append(f"anexos: esperado {arq.get('anexos')} arquivo(s)/{arq.get('bytes')} bytes, "
                         f"restaurado {n}/{total}")
    if arq.get("vapid") and not (pasta / "vapid_privada.pem").exists():
        problemas.append("a chave VAPID não está no pacote")
    return not problemas, problemas, manifesto


def _pasta_trabalho():
    base = getattr(settings, "BACKUP_TRABALHO", "") or (Path(settings.DATA_DIR) / ".backup-trabalho")
    Path(base).mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(dir=base)


def fazer_backup(armazenamento=None, agora=None, chave=None, aplicar_retencao=True):
    """Monta, cifra, envia e aplica a retenção. Devolve um dicionário com o resumo (sem dados pessoais)."""
    chave = chave or carregar_chave()
    armazenamento = armazenamento or armazenamento_padrao()
    agora = agora or dt.datetime.now(dt.timezone.utc)
    prefixo = settings.BACKUP_PREFIXO.strip("/")
    nome = f"{prefixo}/{agora.strftime(NOME_RE)}{SUFIXO}" if prefixo else f"{agora.strftime(NOME_RE)}{SUFIXO}"
    trabalho = _pasta_trabalho()
    try:
        pacote, manifesto = montar_pacote(trabalho, agora)
        cifrado = Path(trabalho) / "pacote.enc"
        cifrar(pacote, cifrado, chave)
        tamanho = cifrado.stat().st_size
        armazenamento.enviar(cifrado, nome)
        apagados = []
        if aplicar_retencao:
            chaves = [o.chave for o in armazenamento.listar(prefixo + "/" if prefixo else "")]
            if nome not in chaves:
                raise ErroBackup("O backup enviado não aparece na listagem do armazenamento; retenção não aplicada.")
            for velho in escolher_para_apagar(chaves, settings.BACKUP_RETENCAO_DIAS,
                                              settings.BACKUP_RETENCAO_SEMANAS, settings.BACKUP_RETENCAO_MESES):
                armazenamento.apagar(velho)
                apagados.append(velho)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
    banco = manifesto.get("banco") or {}
    return {"chave": nome, "bytes": tamanho, "tabelas": len(banco.get("tabelas") or {}),
            "linhas": sum((banco.get("tabelas") or {}).values()), "anexos": manifesto["arquivos"]["anexos"],
            "apagados": apagados}


def ultimo_backup(armazenamento):
    prefixo = settings.BACKUP_PREFIXO.strip("/")
    chaves = [o.chave for o in armazenamento.listar(prefixo + "/" if prefixo else "") if data_do_nome(o.chave)]
    if not chaves:
        raise ErroBackup("Nenhum backup encontrado no armazenamento.")
    return max(chaves, key=data_do_nome)


def restaurar(chave_objeto=None, destino=None, armazenamento=None, chave=None):
    """Baixa, decifra, extrai e confere. Sem ``destino``, extrai numa pasta temporária e apaga ao final (teste de
    restauração). Nunca escreve em ``DATA_DIR`` diretamente: trocar os dados de produção é um passo manual."""
    chave = chave or carregar_chave()
    armazenamento = armazenamento or armazenamento_padrao()
    chave_objeto = chave_objeto or ultimo_backup(armazenamento)
    trabalho = _pasta_trabalho()
    try:
        cifrado = Path(trabalho) / "baixado.enc"
        armazenamento.baixar(chave_objeto, cifrado)
        pacote = Path(trabalho) / "pacote.tar.gz"
        decifrar(cifrado, pacote, chave)
        cifrado.unlink()
        if destino:
            destino = Path(destino)
            if destino.exists() and any(destino.iterdir()):
                raise ErroBackup(f"A pasta {destino} não está vazia. Use uma pasta nova.")
            if destino.resolve() == Path(settings.DATA_DIR).resolve():
                raise ErroBackup("Não restaure direto em DATA_DIR. Use uma pasta nova e siga o procedimento.")
            destino.mkdir(parents=True, exist_ok=True)
            alvo = destino
        else:
            alvo = Path(trabalho) / "extraido"
            alvo.mkdir()
        _extrair(pacote, alvo)
        ok, problemas, manifesto = conferir_extraido(alvo)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
    return {"chave": chave_objeto, "ok": ok, "problemas": problemas,
            "criado_em": (manifesto or {}).get("criado_em"), "destino": str(destino) if destino else None}
