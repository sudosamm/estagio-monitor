"""Multiescola, passo 2 de 3: cria a escola atual a partir da Configuracao e associa todos os registros a ela.

Ida:
- cria a rede SEDUC/CE (a primeira ``RedeEnsino``, com o SICE e o brasão de hoje) e a escola atual com o nome, o
  município e o contato de privacidade da ``Configuracao`` existente; a configuração passa a ser dessa escola;
- grava ``escola`` em todas as linhas das entidades da escola;
- cria os vínculos: cada conta ganha o vínculo com o papel dela; os administradores, também o vínculo ``ADMIN``;
- compara a contagem de linhas de cada tabela antes e depois (nada pode sumir nem aparecer) e confere que não
  sobrou linha sem escola. Qualquer diferença desfaz tudo (a migration roda numa transação).

Volta (só com uma escola no banco): limpa a coluna ``escola``, apaga os vínculos, a escola e a rede criadas e
compara as contagens de novo.

Num banco novo (instalação nova, testes), cria a escola "Escola" com uma configuração em branco.
"""
from django.conf import settings
from django.db import migrations
from django.utils.text import slugify

COM_ESCOLA = [
    "agendamento", "anonimizacao", "avisoexterno", "candidatura", "comunicado", "curso", "diasemestagio",
    "documento", "encerramento", "estagio", "folhaenviada", "linkconfirmacao", "localestagio", "perguntaavaliacao",
    "tipodocumento", "vinculoresponsavel",
    # opcionais (vazio = da plataforma); os registros antigos são todos da escola atual
    "errosistema", "notificacao", "registroacao", "sugestao", "modeloemail",
]
CABECALHO_PADRAO = "Coordenadoria de Educação Profissional\nCélula de Estágio - CEPAE"


def contagens(apps, db):
    saida = {}
    for modelo in apps.get_app_config("core").get_models():
        saida[modelo._meta.label] = modelo._base_manager.using(db).count()
    return saida


def _slug_livre(Escola, db, base):
    base = (base or "escola")[:50]
    slug, n = base, 1
    while Escola.objects.using(db).filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def preencher(apps, schema_editor):
    db = schema_editor.connection.alias
    Escola = apps.get_model("escolas", "Escola")
    Rede = apps.get_model("escolas", "RedeEnsino")
    Vinculo = apps.get_model("escolas", "VinculoEscola")
    Config = apps.get_model("core", "Configuracao")
    Usuario = apps.get_model("core", "Usuario")
    antes = contagens(apps, db)
    if Escola.objects.using(db).exists():
        escola = Escola.objects.using(db).order_by("pk").first()  # rodando de novo depois de uma reversão parcial
    else:
        cfg = Config.objects.using(db).order_by("pk").first()
        rede, _ = Rede.objects.using(db).get_or_create(
            nome=getattr(settings, "NOME_INSTITUICAO", "") or "Secretaria da Educação do Ceará", uf="CE",
            defaults={"secretaria": "SEDUC", "sistema_oficial": "SICE",
                      "sistema_oficial_url": getattr(cfg, "sice_url", "") or "",
                      "brasao_estatico": "img/brasao-ceara-seduc.png", "cabecalho_folha": CABECALHO_PADRAO,
                      "fuso": settings.TIME_ZONE})
        nome = (getattr(cfg, "nome_escola", "") or "").strip() or "Escola"
        escola = Escola.objects.using(db).create(
            nome=nome, slug=_slug_livre(Escola, db, slugify(nome)), rede=rede, situacao="ATIVA",
            municipio=getattr(cfg, "municipio_escola", "") or "", uf="CE",
            encarregado_dados=getattr(cfg, "contato_privacidade", "") or "")
    if not Config.objects.using(db).filter(escola=escola).exists():
        cfg = Config.objects.using(db).filter(escola__isnull=True).order_by("pk").first()
        if cfg is None:
            Config.objects.using(db).create(escola=escola)  # banco novo: a única linha nova esperada
            antes["core.Configuracao"] += 1
        else:
            Config.objects.using(db).filter(pk=cfg.pk).update(escola=escola)
    for nome in COM_ESCOLA:
        apps.get_model("core", nome)._base_manager.using(db).filter(escola__isnull=True).update(escola=escola)
    novos = []
    ja = set(Vinculo.objects.using(db).values_list("usuario_id", "escola_id", "papel"))
    for pk, papel, ativo, admin, entrada in Usuario.objects.using(db).values_list(
            "pk", "papel", "is_active", "is_superuser", "date_joined"):
        papeis = [papel] + (["ADMIN"] if admin else [])
        for p in papeis:
            if (pk, escola.pk, p) not in ja:
                novos.append(Vinculo(usuario_id=pk, escola=escola, papel=p, ativo=ativo, inicio=entrada.date()))
    Vinculo.objects.using(db).bulk_create(novos, batch_size=500)
    depois = contagens(apps, db)
    if antes != depois:
        diferentes = {k: (antes.get(k), depois.get(k)) for k in set(antes) | set(depois) if antes.get(k) != depois.get(k)}
        raise RuntimeError(f"Contagens mudaram na associação à escola: {diferentes}")
    obrigatorias = COM_ESCOLA[:16]
    for nome in obrigatorias:
        sem = apps.get_model("core", nome)._base_manager.using(db).filter(escola__isnull=True).count()
        if sem:
            raise RuntimeError(f"{nome}: {sem} linha(s) ficaram sem escola.")
    if Config.objects.using(db).filter(escola__isnull=True).exists():
        raise RuntimeError("Sobrou configuração sem escola.")
    _limpar_cache()


def desfazer(apps, schema_editor):
    db = schema_editor.connection.alias
    Escola = apps.get_model("escolas", "Escola")
    Rede = apps.get_model("escolas", "RedeEnsino")
    Vinculo = apps.get_model("escolas", "VinculoEscola")
    Config = apps.get_model("core", "Configuracao")
    if Escola.objects.using(db).count() > 1:
        raise RuntimeError("Há mais de uma escola: a reversão juntaria dados de escolas diferentes. Não é possível.")
    antes = contagens(apps, db)
    for nome in COM_ESCOLA:
        apps.get_model("core", nome)._base_manager.using(db).update(escola=None)
    Config.objects.using(db).update(escola=None)
    Vinculo.objects.using(db).all().delete()
    Escola.objects.using(db).all().delete()
    Rede.objects.using(db).filter(escolas__isnull=True).delete()
    depois = contagens(apps, db)
    if antes != depois:
        raise RuntimeError("Contagens mudaram ao desfazer a associação à escola.")
    _limpar_cache()


def _limpar_cache():
    from escolas.escopo import limpar_cache_escola_unica

    limpar_cache_escola_unica()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0047_escola_nas_entidades"),
        ("escolas", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(preencher, desfazer),
    ]
