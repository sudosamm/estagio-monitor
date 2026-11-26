"""Check-in por QR code: o supervisor mostra um código que muda a cada 20 segundos; o estagiário escaneia com a
câmera do celular e a presença já sai confirmada pelo supervisor (ele estava junto)."""
import io

from django.core import signing
from django.utils.crypto import get_random_string

SALT = "estagio-monitor.checkin-qr"
TROCA = 20  # segundos entre um código e outro
VALIDADE = 90  # segundos que um código continua valendo depois de gerado (tempo de abrir a câmera)
SESSAO = "checkin_qr"
SESSAO_VALIDADE = 600  # tempo para entrar no sistema, se o estagiário não estava logado


def gerar(supervisor):
    from escolas.escopo import escola_corrente_ou_nada

    return signing.dumps({"s": supervisor.pk, "e": escola_corrente_ou_nada(), "n": get_random_string(4)}, salt=SALT,
                         compress=True)


def escola_do_token(token, max_age=VALIDADE):
    """Id da escola em que o QR foi gerado (None em códigos antigos)."""
    try:
        return signing.loads(token, salt=SALT, max_age=max_age).get("e")
    except (signing.BadSignature, AttributeError):
        return None


def ler(token, max_age=VALIDADE):
    """Id do supervisor, ou None se o código for inválido ou tiver expirado."""
    try:
        return int(signing.loads(token, salt=SALT, max_age=max_age)["s"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None


def svg(url):
    import segno

    saida = io.BytesIO()
    segno.make(url, error="m", micro=False).save(saida, kind="svg", scale=1, border=2, xmldecl=False, omitsize=True,
                                                   dark="#000", light="#fff")
    return saida.getvalue().decode()
