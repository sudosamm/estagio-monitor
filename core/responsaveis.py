"""Responsáveis legais dos estudantes: acompanham o estágio numa área própria, só de leitura (presenças, horas,
visitas do orientador e avisos da turma). A conta é criada pela escola, a partir do TCE ou a pedido do responsável;
não existe cadastro aberto. O acesso não acaba quando o estudante faz 18 anos: é transparência com quem fez a
matrícula. A importação pelo TCE pula estudantes que começaram o estágio já com 18 anos (nesses casos, só a pedido)."""
from django.db import transaction
from django.utils import timezone

from .models import Estagio, Usuario, VinculoResponsavel
from .validators import cpf_valido, formatar_cpf


def estudantes_de(responsavel):
    return Usuario.objects.filter(responsaveis_legais__responsavel=responsavel,
                                  responsaveis_legais__encerrado_em__isnull=True).distinct()


def estagios_do_responsavel(responsavel):
    return (Estagio.objects.filter(estagiario__in=estudantes_de(responsavel))
            .select_related("estagiario", "local", "supervisor", "orientador", "curso", "turma"))


def vinculos_de(estagiario):
    return (VinculoResponsavel.objects.filter(estagiario=estagiario, encerrado_em__isnull=True)
            .select_related("responsavel"))


def responsaveis_de(estagiarios):
    """Contas ativas dos responsáveis com acesso aos estudantes informados."""
    ids = [getattr(e, "pk", e) for e in estagiarios]
    return list(Usuario.objects.filter(is_active=True, estudantes_acompanhados__estagiario_id__in=ids,
                                       estudantes_acompanhados__encerrado_em__isnull=True).distinct())


def idade_em(nascimento, dia):
    return dia.year - nascimento.year - ((dia.month, dia.day) < (nascimento.month, nascimento.day))


def maior_no_inicio(estagiario):
    """O estudante começou o estágio já com 18 anos? (Sem data de nascimento: não dá para saber → False.)"""
    if not estagiario.data_nascimento:
        return False
    inicio = (Estagio.objects.filter(estagiario=estagiario).order_by("data_inicio")
              .values_list("data_inicio", flat=True).first()) or timezone.localdate()
    return idade_em(estagiario.data_nascimento, inicio) >= 18


@transaction.atomic
def vincular(estagiario, nome, cpf="", telefone="", email="", parentesco="", origem=VinculoResponsavel.Origem.TCE,
             criado_por=None):
    """Cria (ou reaproveita pelo CPF, no caso de irmãos) a conta do responsável e o vínculo com o estudante.
    Devolve (responsavel, conta_nova, vinculo_novo)."""
    from .services import criar_usuario

    cpf = formatar_cpf(cpf) if cpf and cpf_valido(cpf) else ""
    resp = Usuario.objects.filter(papel=Usuario.Papel.RESPONSAVEL, cpf=cpf).first() if cpf else None
    nova = resp is None
    if nova:
        extra = {k: v for k, v in {"cpf": cpf, "telefone": telefone.strip(), "email": email.strip()}.items() if v}
        resp = criar_usuario(nome, Usuario.Papel.RESPONSAVEL, criado_por, **extra)
    else:  # completa o que faltava
        mudou = [c for c, v in (("telefone", telefone.strip()), ("email", email.strip())) if v and not getattr(resp, c)]
        for c in mudou:
            setattr(resp, c, {"telefone": telefone, "email": email}[c].strip())
        if mudou:
            resp.save(update_fields=mudou)
    vinculo, criado = VinculoResponsavel.objects.get_or_create(
        estagiario=estagiario, responsavel=resp,
        defaults={"parentesco": parentesco.strip()[:40], "origem": origem, "criado_por": criado_por})
    if not criado and vinculo.encerrado_em:  # volta a ter acesso
        vinculo.encerrado_em = vinculo.encerrado_por = None
        vinculo.parentesco = parentesco.strip()[:40] or vinculo.parentesco
        vinculo.save()
        criado = True
    return resp, nova, criado


def encerrar(vinculo, usuario):
    vinculo.encerrado_em, vinculo.encerrado_por = timezone.now(), usuario
    vinculo.save(update_fields=["encerrado_em", "encerrado_por"])
    # sem nenhum estudante para acompanhar, a conta fica inativa (e sai de todos os aparelhos)
    if not vinculo.responsavel.estudantes_acompanhados.filter(encerrado_em__isnull=True).exists():
        vinculo.responsavel.is_active = False
        vinculo.responsavel.save(update_fields=["is_active"])


def notificar_responsaveis(estagiario, texto, link="", detalhe="", email=True):
    from .services import notificar

    notificar(responsaveis_de([estagiario]), texto, link, detalhe=detalhe, email=email)


def mensagem_acesso(usuario, codigo, endereco, escola, estudantes=()):
    """Texto do primeiro acesso para mandar pelo WhatsApp (a escola só toca em Enviar)."""
    de = f" para acompanhar o estágio de {', '.join(estudantes)}" if estudantes else ""
    return (f"Olá, {usuario.primeiro_nome}! A {escola} criou o seu acesso ao sistema de acompanhamento de estágio{de}. "
            f"Abra {endereco}, escolha “Tenho um código” e informe o usuário {usuario.username} e o código {codigo}. "
            "Depois é só criar a sua senha. O código vale 30 dias e uma vez só.")


def link_whatsapp(telefone, texto):
    from urllib.parse import quote

    from .confirmacao import telefone_whatsapp

    numero = telefone_whatsapp(telefone)
    return f"https://wa.me/{numero}?text={quote(texto)}" if numero else ""
