"""Mantém os vínculos com a escola em sincronia com ``Usuario.papel`` e ``is_superuser`` (compatibilidade de 2027).

Quem cria e edita contas continua usando ``Usuario.papel`` (o papel principal). Ao salvar, a conta ganha (ou
atualiza) o vínculo com a escola em uso:
- conta nova: vínculo com o papel dela; administrador gravado (``is_superuser``) ganha também o vínculo ``ADMIN``;
- papel trocado: o vínculo do papel antigo nesta escola é encerrado (fica no histórico) e o novo é criado;
- deixou de ser administrador: o vínculo ``ADMIN`` desta escola é encerrado.
Fora de uma escola definida (ex.: ``createsuperuser`` num banco com várias escolas) nada é criado: a conta fica só
na plataforma.
"""
from django.utils import timezone


def sincronizar(usuario, criado, papel_antes, admin_antes):
    from .escopo import TODAS, escola_corrente
    from .models import VinculoEscola

    if not criado and papel_antes == usuario.papel and admin_antes == usuario.is_superuser:
        return
    escola = escola_corrente(obrigatoria=False)
    if escola is None or escola is TODAS:
        return
    hoje = timezone.localdate()
    if not criado and papel_antes and papel_antes != usuario.papel:
        VinculoEscola.objects.filter(usuario=usuario, escola=escola, papel=papel_antes, ativo=True).update(
            ativo=False, fim=hoje)
    v, novo = VinculoEscola.objects.get_or_create(usuario=usuario, escola=escola, papel=usuario.papel)
    if not novo and not v.ativo:
        VinculoEscola.objects.filter(pk=v.pk).update(ativo=True, fim=None)
    if usuario.is_superuser:
        a, novo = VinculoEscola.objects.get_or_create(usuario=usuario, escola=escola, papel=VinculoEscola.Papel.ADMIN_ESCOLA)
        if not novo and not a.ativo:
            VinculoEscola.objects.filter(pk=a.pk).update(ativo=True, fim=None)
    elif admin_antes:
        VinculoEscola.objects.filter(usuario=usuario, escola=escola, papel=VinculoEscola.Papel.ADMIN_ESCOLA,
                                     ativo=True).update(ativo=False, fim=hoje)
