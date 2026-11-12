"""Pasta do estágio: documentos exigidos de cada estagiário, quem envia, prazo e conferência pela escola."""
from dataclasses import dataclass
from datetime import date

from django.urls import reverse
from django.utils import timezone

from .models import Documento, TipoDocumento
from .services import notificar

ROTULOS = {
    "conferido": "Conferido",
    "enviado": "Aguardando conferência",
    "recusado": "Recusado — enviar de novo",
    "atrasado": "Atrasado",
    "pendente": "Pendente",
    "depois": "No fim do estágio",
    "opcional": "Opcional",
}


@dataclass
class ItemPasta:
    tipo: TipoDocumento
    doc: Documento | None
    codigo: str
    prazo: date | None

    @property
    def rotulo(self):
        return ROTULOS[self.codigo]

    @property
    def falta(self):
        """Ainda precisa de alguém enviar (pendente, atrasado ou recusado)."""
        return self.codigo in ("pendente", "atrasado", "recusado")


def tipos_ativos():
    return list(TipoDocumento.objects.filter(ativo=True))


def pasta_do_estagio(estagio, hoje=None, tipos=None, docs=None):
    """Um item por documento exigido, com a entrega mais recente e a situação."""
    hoje = hoje or timezone.localdate()
    tipos = [t for t in (tipos if tipos is not None else tipos_ativos()) if t.vale_para(estagio)]
    if docs is None:
        docs = list(estagio.documentos.filter(tipo__isnull=False).select_related("enviado_por", "analisado_por"))
    ultimo = {}
    for d in sorted(docs, key=lambda d: d.criado_em):
        if d.situacao == Documento.Situacao.APROVADO or ultimo.get(d.tipo_id) is None \
                or ultimo[d.tipo_id].situacao != Documento.Situacao.APROVADO:
            ultimo[d.tipo_id] = d
    itens = []
    for t in tipos:
        doc = ultimo.get(t.pk)
        prazo = t.prazo_para(estagio)
        if doc and doc.situacao == Documento.Situacao.APROVADO:
            codigo = "conferido"
        elif doc and doc.situacao == Documento.Situacao.ENVIADO:
            codigo = "enviado"
        elif doc and doc.situacao == Documento.Situacao.RECUSADO:
            codigo = "recusado"
        elif t.momento == TipoDocumento.Momento.FIM and estagio.ativo and (not estagio.data_fim or hoje < estagio.data_fim):
            codigo = "depois" if t.obrigatorio else "opcional"
        elif not t.obrigatorio:
            codigo = "opcional"
        elif prazo and hoje > prazo:
            codigo = "atrasado"
        else:
            codigo = "pendente"
        itens.append(ItemPasta(t, doc, codigo, prazo))
    return itens


def resumo_pasta(itens):
    return {
        "total": sum(1 for i in itens if i.tipo.obrigatorio),
        "conferidos": sum(1 for i in itens if i.codigo == "conferido" and i.tipo.obrigatorio),
        "enviados": sum(1 for i in itens if i.codigo == "enviado"),
        "atrasados": [i for i in itens if i.codigo in ("atrasado", "recusado") and i.tipo.obrigatorio],
    }


def pastas(estagios, hoje=None):
    """{estagio.pk: itens} para vários estágios, com poucas consultas."""
    tipos = tipos_ativos()
    por_estagio = {}
    for d in (Documento.objects.filter(estagio__in=estagios, tipo__isnull=False)
              .select_related("enviado_por", "analisado_por")):
        por_estagio.setdefault(d.estagio_id, []).append(d)
    return {e.pk: pasta_do_estagio(e, hoje, tipos, por_estagio.get(e.pk, [])) for e in estagios}


def pode_enviar(usuario, estagio):
    from .views.base import eh_orientador_do, eh_supervisor_do

    return (usuario.pk == estagio.estagiario_id or eh_supervisor_do(usuario, estagio)
            or eh_orientador_do(usuario, estagio))


def registrar_entrega(estagio, tipo, usuario, arquivo, observacao="", avisar=True):
    """Guarda o arquivo na pasta. Enviado pela escola já sai conferido; os demais aguardam a conferência.

    Sem arquivo (só a escola): o documento foi entregue em papel e está guardado na escola."""
    from .views.base import eh_orientador_do

    escola = eh_orientador_do(usuario, estagio)
    doc = Documento(
        titulo=tipo.nome[:160], categoria=Documento.Categoria.OUTRO, arquivo=arquivo or "",
        nome_original=getattr(arquivo, "name", "")[:255], estagio=estagio, orientador=estagio.orientador,
        enviado_por=usuario, descricao=observacao or ("" if arquivo else "Entregue em papel na escola."), tipo=tipo,
        situacao=Documento.Situacao.APROVADO if escola else Documento.Situacao.ENVIADO,
    )
    if escola:
        doc.analisado_por, doc.analisado_em = usuario, timezone.now()
    doc.save()
    link = estagio.get_absolute_url() + "?aba=arquivos"
    if not avisar:
        return doc
    if escola:
        notificar([estagio.estagiario], f"{usuario.primeiro_nome} incluiu “{tipo.nome}” na sua pasta do estágio.", link,
                  exceto=usuario)
    else:
        notificar([estagio.orientador], f"{usuario.primeiro_nome} enviou “{tipo.nome}” de "
                  f"{estagio.estagiario.primeiro_nome} para conferência.", link, exceto=usuario)
    return doc


def conferir(doc, usuario, aprovar, parecer=""):
    doc.situacao = Documento.Situacao.APROVADO if aprovar else Documento.Situacao.RECUSADO
    doc.analisado_por, doc.analisado_em, doc.parecer = usuario, timezone.now(), parecer
    doc.save(update_fields=["situacao", "analisado_por", "analisado_em", "parecer"])
    e = doc.estagio
    texto = (f"“{doc.tipo.nome if doc.tipo else doc.titulo}” de {e.estagiario.primeiro_nome} foi conferido."
             if aprovar else f"“{doc.tipo.nome if doc.tipo else doc.titulo}” de {e.estagiario.primeiro_nome} foi "
                             f"recusado: {parecer[:90]}. Envie de novo.")
    notificar([e.estagiario, doc.enviado_por], texto, reverse("estagio_detalhe", args=[e.pk]) + "?aba=arquivos",
              exceto=usuario)
    return doc
