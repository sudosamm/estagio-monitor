# 01 — Inventário das telas por perfil

Levantado de `monitor/urls.py` e de `core/views/*.py` em 25/11/2026 (170 rotas com nome, mais `/admin/` e `/saude/`).
A coluna "Acesso" mostra o decorador da view e as checagens feitas dentro dela. Siglas:

- **"painel"**, **"contas"** etc.: `@permissao(nome)`, que consulta `PERMISSOES_POR_PAPEL` em `core/models.py`.
  `@orientador_requerido` é `@permissao("painel")`.
- **papel SUPERVISOR**: `@papel(...)` (o superusuário sempre passa).
- **pegar_estagio**: abre o estágio e chama `Estagio.pode_ver` (estagiário, orientador, supervisor, coordenador do
  curso ou administrador). Com `apoio=True`, também o responsável pela concedente e o substituto do supervisor.
- **eh_orientador_do / eh_supervisor_do / pode_ver / pode_decidir**: checagem por objeto, dentro da view.
- **POST**: `@require_POST`.

## Como as permissões se combinam hoje

| Papel (`Usuario.papel`) | Permissões | Observação |
|---|---|---|
| Administrador (`is_superuser`) | todas | `Usuario.save` força `papel = ORIENTADOR`. Com o "modo administrador" desligado, o `ModoAdministradorMiddleware` tira o `is_superuser` só durante a requisição |
| ORIENTADOR | todas as 13 de `PERMISSOES` | vê só os próprios estagiários (`estagios_visiveis`) |
| COORDENADOR | painel, estagiarios, contas, cadastros, candidaturas, frequencias | vê os estágios dos cursos que coordena (vazio = todos) |
| SUPERVISOR | — (área própria) | responsável pela concedente quando tem `concedentes_geridas`; substituto por `Substituicao` |
| ESTAGIARIO | — (área própria) | |
| RESPONSAVEL | — (área própria, só leitura) | `AreaDoResponsavelMiddleware` libera só uma lista fixa de rotas |

Barreiras globais, antes de qualquer view: `TrocaSenhaObrigatoriaMiddleware` (primeiro acesso, 2FA exigida, aceite dos
termos) e `AreaDoResponsavelMiddleware`. A auditoria (`AuditoriaMiddleware`) registra os POSTs da gestão.

## Menus atuais

- **Gestão** (`menu_gestor` em `core/context_processors.py`): "Painel" e "Estagiários" soltos; seções
  **Acompanhamento** (11 itens: indicadores, resumo da semana, agenda, mapa, roteiro, frequências, feedback,
  avaliações SICE, atestados, pasta de documentos, alterar dias), **Comunicação** (avisos, arquivos gerais, opiniões),
  **Cadastros** (contas, concedentes, turmas e cursos, feriados/recessos, captação, banco de talentos, encerramento) e
  **Sistema** (configurações, e-mails automáticos, registro de ações, erros). Busca global (`/buscar/`, atalho `/`).
- **Supervisor** (em `templates/base.html`): Meus estagiários, Equipe (se responsável pela concedente), Visitas e
  conversas, Dias e horários, Recessos, Frequências, Banco de talentos (se aberto). Sem vínculo aprovado: só "Cadastro
  da concedente".
- **Estagiário**: Meu estágio, Folha de frequência, Visitas e conversas, Avaliações (se abertas).
- **Responsável legal**: Acompanhar o estágio, Avisos da escola.
- **Menu do usuário** (todos): Meus dados, Alterar senha, O que há de novo, Sugestões e erros, Instalar no celular,
  Tema; para o administrador, Configurações e Administração (`/admin/`).

Observações para a Etapa 3:

- O menu da gestão é montado em Python, mas os menus dos outros perfis estão no template. Não há uma fonte única.
- "Configurações" aparece no menu "Sistema" e também no menu do usuário (link duplicado).
- Algumas telas da gestão não estão em nenhum menu e só são achadas por dentro de outras: `relatorio_turma`,
  `declaracao_estagio`, `importar_csv`, `importar_responsaveis`, `tipos_documento`, `perguntas_avaliacao`,
  `assinar_agenda`, `avaliacoes_sobre_mim`.
- Três telas checam `is_superuser` à mão, sem decorador (`sistema.erros`, `sistema.acoes`, `orientador.configuracoes`).
  Funciona, mas uma fonte única de permissões evita esquecer uma checagem.

### Público (sem login)

| URL | Nome | View | Acesso (decorador · checagem no código) | Template |
|---|---|---|---|---|
| `/entrar/` | `login` | `dois_fatores.EntrarView` | aberta | registration/login.html |
| `/entrar/verificacao/` | `verificar_dois_fatores` | `dois_fatores.verificar` | aberta | registration/verificar_dois_fatores.html |
| `/privacidade/` | `privacidade` | `legal.privacidade` | aberta | privacidade.html |
| `/termos/` | `termos` | `legal.termos_de_uso` | aberta | termos.html |
| `/s/<str:codigo>/` | `confirmar_por_link` | `confirmacao.confirmar_por_link` | aberta · código de uso único (SHA-256, 7 dias) | confirmar_link.html |
| `/primeiro-acesso/` | `primeiro_acesso` | `primeiro_acesso.primeiro_acesso` | aberta | registration/primeiro_acesso.html |
| `/senha/esqueci/` | `esqueci_senha` | `conta.esqueci_senha` | aberta | registration/esqueci_senha.html |
| `/senha/nova/<uidb64>/<token>/` | `redefinir_senha_email` | `conta.RedefinirSenhaView` | aberta · token do Django (2 h) | registration/redefinir_senha.html |
| `/acesso/ajuda/` | `pedir_ajuda` | `conta.pedir_ajuda` | aberta (o pedido vai aos administradores) | registration/pedir_ajuda.html |
| `/primeiro-acesso/senha/` | `primeiro_acesso_senha` | `primeiro_acesso.primeiro_acesso_senha` | aberta | registration/primeiro_acesso_senha.html |
| `/email/confirmar/<str:token>/` | `confirmar_email` | `comum.confirmar_email` | aberta · token assinado (3 dias) | — (redireciona/arquivo) |
| `/sugestoes/` | `sugestoes` | `novidades.sugestoes` | aberta (com ou sem login) | sugestoes.html |
| `/seja-concedente/` | `candidatura_publica` | `captacao.candidatura_publica` | aberta | captacao_publica.html |
| `/p/<str:token>/` | `checkin_qr` | `qrcheckin.checkin_qr` | aberta · token assinado (90 s) + login | qr_estagiario.html |
| `/agenda/calendario/<str:token>.ics` | `agenda_ics` | `agenda.agenda_ics` | aberta · token secreto do usuário | — (.ics) |
| `/manifest.webmanifest` | `manifesto` | `pwa.manifesto` | aberta | — (JSON) |
| `/sw.js` | `service_worker` | `pwa.service_worker` | aberta | pwa/sw.js |
| `/offline/` | `offline` | `pwa.offline` | aberta | pwa/offline.html |

### Conta (todos os perfis logados)

| URL | Nome | View | Acesso (decorador · checagem no código) | Template |
|---|---|---|---|---|
| `/` | `inicio` | `comum.inicio` | login | estagiario_lista.html |
| `/termos/aceitar/` | `aceitar_termos` | `legal.aceitar_termos` | login | aceitar_termos.html |
| `/perfil/meus-dados/` | `baixar_meus_dados` | `legal.baixar_meus_dados` | login | — (.json/.zip) |
| `/perfil/verificacao/` | `dois_fatores` | `dois_fatores.configurar` | login | dois_fatores.html |
| `/sair/` | `logout` | `auth_views.LogoutView` | aberta | — (redireciona/arquivo) |
| `/senha/` | `trocar_senha` | `comum.trocar_senha` | login | trocar_senha.html |
| `/perfil/` | `perfil` | `comum.perfil` | login | perfil.html |
| `/perfil/email/reenviar/` | `reenviar_confirmacao` | `comum.reenviar_confirmacao` | login POST | — (redireciona/arquivo) |
| `/perfil/acessos/` | `acessos` | `acessos.acessos` | login | acessos.html |
| `/perfil/modo/` | `alternar_modo` | `comum.alternar_modo` | login POST | — (redireciona/arquivo) |
| `/tema/` | `trocar_tema` | `comum.trocar_tema` | login POST | — (redireciona/arquivo) |
| `/novidades/` | `novidades` | `novidades.novidades` | login · is_superuser | novidades.html |
| `/novidades/visto/` | `novidades_visto` | `novidades.novidades_visto` | login POST | — (redireciona/arquivo) |
| `/opiniao/` | `enviar_opiniao` | `opinioes.enviar_opiniao` | login POST · is_superuser | — (redireciona/arquivo) |
| `/notificacoes/` | `notificacoes` | `comum.notificacoes` | login | notificacoes.html |
| `/notificacoes/lidas/` | `notificacoes_lidas` | `comum.notificacoes_marcar_lidas` | login POST | — (redireciona/arquivo) |
| `/notificacoes/<int:pk>/` | `notificacao_abrir` | `comum.notificacao_abrir` | login | — (redireciona/arquivo) |
| `/push/chave/` | `push_chave` | `avisos.push_chave` | login | — (redireciona/arquivo) |
| `/push/inscrever/` | `push_inscrever` | `avisos.push_inscrever` | login POST | — (redireciona/arquivo) |
| `/push/cancelar/` | `push_cancelar` | `avisos.push_cancelar` | login POST | — (redireciona/arquivo) |
| `/push/teste/` | `push_teste` | `avisos.push_teste` | login POST | — (redireciona/arquivo) |
| `/comunicados/recebidos/` | `meus_comunicados` | `avisos.meus_comunicados` | login | comunicados_recebidos.html |
| `/comunicados/<int:pk>/` | `comunicado` | `avisos.comunicado` | login · is_superuser | comunicado.html |
| `/usuarios/<int:pk>/foto/` | `foto_usuario` | `comum.foto_usuario` | login | — (redireciona/arquivo) |
| `/usuarios/<int:pk>/curriculo/` | `curriculo_usuario` | `comum.curriculo_usuario` | login | — (redireciona/arquivo) |
| `/folha/logo/` | `logo_folha` | `comum.logo_folha` | login | — (redireciona/arquivo) |
| `/arquivos/<int:pk>/` | `baixar_documento` | `comum.baixar_documento` | login · pode_ver | — (redireciona/arquivo) |

### Estágio (estagiário, supervisor, gestão — checagem por objeto)

| URL | Nome | View | Acesso (decorador · checagem no código) | Template |
|---|---|---|---|---|
| `/talentos/` | `banco_talentos` | `comum.banco_talentos` | login | talentos.html |
| `/arquivos/<int:pk>/excluir/` | `excluir_documento` | `comum.excluir_documento` | login POST · is_superuser | — (redireciona/arquivo) |
| `/estagios/<int:pk>/` | `estagio_detalhe` | `estagio.estagio_detalhe` | login · eh_orientador_do, eh_supervisor_do, pegar_estagio, pode_ver; usa "agenda" | estagio_detalhe.html |
| `/estagios/<int:pk>/presenca/` | `marcar_presenca` | `estagio.marcar_presenca` | login POST · pegar_estagio | — (redireciona/arquivo) |
| `/estagios/<int:pk>/saida/` | `registrar_saida` | `estagio.registrar_saida` | login POST · pegar_estagio | — (redireciona/arquivo) |
| `/estagios/<int:pk>/ausencia/` | `informar_ausencia` | `estagio.informar_ausencia` | login POST · pegar_estagio | — (redireciona/arquivo) |
| `/estagios/<int:pk>/atestado/` | `enviar_atestado` | `atestados.enviar_atestado` | login · eh_orientador_do, pegar_estagio | _atestados_lista.html, form_pagina.html |
| `/estagios/<int:pk>/feedback/` | `dar_feedback` | `feedback.dar_feedback` | login · eh_supervisor_do, pegar_estagio | feedback_form.html |
| `/acompanhamentos/<int:pk>/` | `acompanhamento_ver` | `visitas.acompanhamento_ver` | login | acompanhamento_ver.html |
| `/avaliacoes/` | `minhas_avaliacoes` | `avaliacoes.minhas_avaliacoes` | login | avaliacoes_estagiario.html |
| `/avaliacoes/ver/<int:pk>/` | `ver_avaliacao` | `avaliacoes.ver_avaliacao` | login | avaliacao_ver.html |
| `/avaliacoes/<str:tipo>/<str:mes>/` | `responder_avaliacao` | `avaliacoes.responder_avaliacao` | login | avaliacao_form.html |
| `/avaliacoes/<str:tipo>/<str:mes>/sice/` | `copiar_avaliacao` | `avaliacoes.copiar_avaliacao` | login | avaliacao_copiar.html |
| `/atestados/<int:pk>/` | `atestado_detalhe` | `atestados.atestado_detalhe` | login · pode_decidir | atestado.html |
| `/atestados/<int:pk>/arquivo/` | `atestado_arquivo` | `atestados.atestado_arquivo` | login | — (redireciona/arquivo) |
| `/atestados/<int:pk>/decidir/` | `decidir_atestado` | `atestados.decidir_atestado` | login POST · pode_decidir | — (redireciona/arquivo) |
| `/estagios/<int:pk>/dia/<str:data>/` | `estagio_dia` | `estagio.estagio_dia` | login · eh_orientador_do, eh_supervisor_do, pegar_estagio, pode_ver | estagio_dia.html |
| `/estagios/<int:pk>/mensagens/` | `enviar_mensagem` | `estagio.enviar_mensagem` | login POST · eh_supervisor_do, pegar_estagio | — (redireciona/arquivo) |
| `/estagios/<int:pk>/arquivos/` | `enviar_documento` | `estagio.enviar_documento` | login POST · pegar_estagio | — (redireciona/arquivo) |
| `/estagios/<int:pk>/frequencia/` | `folha_frequencia` | `frequencia.folha_frequencia` | login · pegar_estagio | folha_frequencia.html |
| `/frequencia/impressa/` | `marcar_impressao` | `frequencia.marcar_impressao` | login POST | — (redireciona/arquivo) |
| `/frequencias/` | `frequencias` | `frequencia.frequencias_painel` | login · "frequencias"/"folhas" ou supervisor | frequencias.html |
| `/frequencias/folhas/<int:pk>/` | `baixar_folha` | `frequencia.baixar_folha` | login | — (redireciona/arquivo) |
| `/estagios/<int:pk>/folhas/` | `minhas_folhas` | `frequencia.minhas_folhas` | login · pegar_estagio | minhas_folhas.html |
| `/estagios/<int:pk>/supervisor/` | `trocar_supervisor` | `estagio.trocar_supervisor_view` | login · eh_orientador_do, pegar_estagio | trocar_supervisor.html |
| `/estagios/<int:pk>/escalas/` | `nova_escala` | `estagio.nova_escala` | login POST · pegar_estagio | — (redireciona/arquivo) |
| `/escalas/<int:pk>/excluir/` | `excluir_escala` | `estagio.excluir_escala` | login POST · pode_ver | — (redireciona/arquivo) |
| `/registros/<int:pk>/validar/` | `validar_registro` | `estagio.validar_registro` | login POST · pode_decidir | — (redireciona/arquivo) |
| `/escalas/alterar/` | `escala_lote` | `orientador.escala_lote` | login · permissão "escalas" ou supervisor | escala_lote.html |
| `/recessos/` | `recessos` | `orientador.recessos` | login · gestão com "cadastros"/"feriados" ou supervisor das concedentes | recessos.html |
| `/documentos/tipos/<int:pk>/modelo/` | `baixar_modelo` | `pasta.baixar_modelo` | login | — (redireciona/arquivo) |
| `/estagios/<int:pk>/pasta/<int:tipo_pk>/` | `enviar_para_pasta` | `pasta.enviar_para_pasta` | login POST · pegar_estagio | — (redireciona/arquivo) |
| `/arquivos/<int:pk>/conferir/` | `conferir_documento` | `pasta.conferir_documento` | login POST · eh_orientador_do | — (redireciona/arquivo) |
| `/p/ok/` | `checkin_qr_confirmar` | `qrcheckin.checkin_qr_confirmar` | login | qr_estagiario.html |
| `/agenda/` | `agendamentos` | `agenda.agendamentos` | login · quem tem agenda (não responsável) | agendamentos.html |
| `/agenda/novo/` | `novo_agendamento` | `agenda.novo_agendamento` | login · is_superuser | agendamento_form.html, form_pagina.html |
| `/agenda/<int:pk>/` | `agendamento_detalhe` | `agenda.agendamento_detalhe` | login · is_superuser | agendamento_detalhe.html |
| `/agenda/<int:pk>/cancelar/` | `cancelar_agendamento` | `agenda.cancelar_agendamento` | login POST · is_superuser | — (redireciona/arquivo) |
| `/agenda/assinar/` | `assinar_agenda` | `agenda.assinar_agenda` | login | assinar_agenda.html |

### Supervisor e responsável pela concedente

| URL | Nome | View | Acesso (decorador · checagem no código) | Template |
|---|---|---|---|---|
| `/captacao/<int:pk>/alterar/` | `editar_candidatura` | `captacao.editar_candidatura` | login · pode_ver; usa "candidaturas" | captacao_publica.html |
| `/cadastro-concedente/` | `minhas_candidaturas` | `captacao.minhas_candidaturas` | login | minhas_candidaturas.html |
| `/cadastro-concedente/<int:pk>/` | `minha_candidatura` | `captacao.minha_candidatura` | login | minha_candidatura.html |
| `/supervisao/` | `painel_supervisor` | `supervisor.painel_supervisor` | papel SUPERVISOR | painel_supervisor.html |
| `/supervisao/confirmar/` | `confirmar_lote` | `supervisor.confirmar_lote` | papel SUPERVISOR POST | — (redireciona/arquivo) |
| `/supervisao/ausencia/` | `indicar_substituto` | `equipe.indicar_substituto` | login POST | — (redireciona/arquivo) |
| `/substituicoes/<int:pk>/encerrar/` | `encerrar_substituicao` | `equipe.encerrar_substituicao` | login POST | — (redireciona/arquivo) |
| `/equipe/` | `minha_equipe` | `equipe.minha_equipe` | login | equipe_escolher.html |
| `/concedentes/<int:pk>/equipe/` | `equipe_concedente` | `equipe.equipe_concedente` | login · usa "contas" | equipe.html |
| `/supervisao/qr/` | `qr_supervisor` | `qrcheckin.qr_supervisor` | papel SUPERVISOR | qr_supervisor.html |
| `/supervisao/qr/novo/` | `qr_novo` | `qrcheckin.qr_novo` | papel SUPERVISOR | — (redireciona/arquivo) |

### Responsável legal

| URL | Nome | View | Acesso (decorador · checagem no código) | Template |
|---|---|---|---|---|
| `/acompanhar/` | `responsavel_inicio` | `responsavel.responsavel_inicio` | login | responsavel_inicio.html |
| `/acompanhar/<int:pk>/` | `responsavel_estagio` | `responsavel.responsavel_estagio` | login | responsavel_estagio.html |

### Gestão (orientador, coordenador; por permissão)

| URL | Nome | View | Acesso (decorador · checagem no código) | Template |
|---|---|---|---|---|
| `/buscar/` | `buscar` | `roteiro.buscar` | "painel" · is_superuser; usa "cadastros", "contas" | — (JSON) |
| `/estagios/<int:pk>/responsaveis/` | `responsaveis_estagio` | `responsavel.responsaveis_estagio` | "estagiarios" POST · eh_orientador_do, pegar_estagio | — (redireciona/arquivo) |
| `/contas/responsaveis/importar/` | `importar_responsaveis` | `responsavel.importar_responsaveis` | "contas" | importar_responsaveis.html |
| `/comunicados/` | `comunicados` | `avisos.comunicados` | "painel" · is_superuser | comunicados.html |
| `/estagios/<int:estagio_pk>/acompanhamento/` | `acompanhamento_novo` | `visitas.acompanhamento_form` | login · eh_orientador_do, pegar_estagio | acompanhamento_form.html |
| `/estagios/<int:estagio_pk>/acompanhamento/<int:pk>/` | `acompanhamento_editar` | `visitas.acompanhamento_form` | login · eh_orientador_do, pegar_estagio | acompanhamento_form.html |
| `/acompanhamentos/<int:pk>/sice/` | `acompanhamento_sice` | `visitas.acompanhamento_sice` | login · eh_orientador_do | acompanhamento_sice.html |
| `/feedback/` | `feedback_geral` | `feedback.feedback_geral` | "painel" | feedback_geral.html |
| `/avaliacoes/escola/` | `avaliacoes_escola` | `avaliacoes.avaliacoes_escola` | "painel" | avaliacoes_escola.html |
| `/avaliacoes/escola/avisar/` | `avisar_avaliacoes` | `avaliacoes.avisar_avaliacoes` | "avaliacoes" POST | — (redireciona/arquivo) |
| `/avaliacoes/sobre-mim/` | `avaliacoes_sobre_mim` | `avaliacoes.avaliacoes_sobre_mim` | "painel" | avaliacoes_sobre_mim.html |
| `/avaliacoes/perguntas/` | `perguntas_avaliacao` | `avaliacoes.perguntas_avaliacao` | "avaliacoes" | perguntas_avaliacao.html |
| `/avaliacoes/perguntas/<int:pk>/` | `pergunta_avaliacao_editar` | `avaliacoes.perguntas_avaliacao` | "avaliacoes" | perguntas_avaliacao.html |
| `/atestados/` | `atestados` | `atestados.atestados` | "painel" | atestados.html |
| `/frequencias/emitir/` | `folhas_lote` | `frequencia.folhas_lote` | "folhas" | folha_frequencia.html (lote) |
| `/frequencias/folhas/<int:pk>/excluir/` | `excluir_folha` | `frequencia.excluir_folha` | "folhas" POST · is_superuser | — (redireciona/arquivo) |
| `/estagios/<int:pk>/editar/` | `editar_estagio` | `estagio.editar_estagio` | "painel" · eh_orientador_do, pegar_estagio | form_pagina.html |
| `/painel/` | `painel` | `orientador.painel` | "painel" · is_superuser | painel_orientador.html |
| `/estagios/` | `estagios_lista` | `orientador.estagios_lista` | "painel" | estagios_lista.html |
| `/estagios/novos/` | `criar_estagiarios` | `orientador.criar_estagiarios` | "estagiarios" | form_pagina.html |
| `/escalas/alterar/importadas-fora/` | `remover_importadas_fora` | `orientador.remover_importadas_fora` | "escalas" POST | — (redireciona/arquivo) |
| `/contas/` | `usuarios` | `orientador.usuarios` | "contas" | usuarios.html |
| `/contas/supervisores/novos/` | `criar_supervisores` | `orientador.criar_supervisores` | "contas" | form_pagina.html |
| `/contas/orientadores/novo/` | `criar_orientador` | `orientador.criar_orientador` | "contas" · is_superuser | form_pagina.html |
| `/contas/coordenadores/novo/` | `criar_coordenador` | `orientador.criar_coordenador` | "contas" · is_superuser | form_pagina.html |
| `/contas/importar/` | `importar_csv` | `importacao.importar_csv` | "painel" · is_superuser (orientador_requerido + checagem) | importar.html |
| `/contas/<int:pk>/` | `editar_usuario` | `orientador.editar_usuario` | "contas" · is_superuser | _redefinir_senha.html, form_pagina.html |
| `/contas/<int:pk>/senha-padrao/` | `redefinir_senha` | `orientador.redefinir_senha` | "contas" POST | — (redireciona/arquivo) |
| `/contas/codigos/` | `codigos_lote` | `orientador.codigos_lote` | "contas" POST · is_superuser | — (redireciona/arquivo) |
| `/contas/<int:pk>/desconectar/` | `desconectar_usuario` | `acessos.desconectar_usuario` | "contas" POST | — (redireciona/arquivo) |
| `/contas/<int:pk>/confirmar-email/` | `pedir_confirmacao_email` | `orientador.pedir_confirmacao_email` | "contas" POST | — (redireciona/arquivo) |
| `/contas/confirmar-emails/` | `confirmacao_lote` | `orientador.confirmacao_lote` | "contas" POST | — (redireciona/arquivo) |
| `/contas/<int:pk>/ativacao/` | `ativacao_usuario` | `orientador.ativacao_usuario` | "contas" · is_superuser | ativacao_usuario.html |
| `/cursos/` | `cursos` | `orientador.cursos` | "cadastros" | cursos.html |
| `/cursos/<int:pk>/` | `curso_editar` | `orientador.cursos` | "cadastros" | cursos.html |
| `/concedentes/` | `locais` | `orientador.locais` | "cadastros" | locais.html |
| `/concedentes/nova/` | `local_novo` | `orientador.local_editar` | "cadastros" | concedente_form.html |
| `/concedentes/<int:pk>/` | `local_editar` | `orientador.local_editar` | "cadastros" | concedente_form.html |
| `/concedentes/<int:pk>/ativacao/` | `ativacao_local` | `orientador.ativacao_local` | "cadastros" | ativacao_local.html |
| `/turmas/<int:pk>/relatorio/` | `relatorio_turma` | `relatorios.relatorio_turma` | "painel" | relatorio_turma.html (ou .xlsx) |
| `/estagios/exportar/` | `exportar_estagios` | `relatorios.exportar_estagios` | "painel" | — (.xlsx/.csv) |
| `/estagios/<int:pk>/declaracao/` | `declaracao_estagio` | `relatorios.declaracao_estagio` | "painel" · eh_orientador_do, pegar_estagio | declaracao.html |
| `/resumo/` | `resumo_semanal` | `relatorios.resumo_semanal_view` | "painel" | resumo_semanal.html |
| `/indicadores/` | `indicadores` | `relatorios.indicadores` | "painel" | indicadores.html |
| `/turmas/` | `turmas` | `orientador.turmas` | "cadastros" · is_superuser | turmas.html |
| `/turmas/<int:pk>/` | `turma_editar` | `orientador.turmas` | "cadastros" · is_superuser | turmas.html |
| `/encerramento/` | `encerramento` | `encerramento.encerramento` | "encerramento" | encerramento.html |
| `/captacao/` | `captacao` | `captacao.captacao_lista` | "candidaturas" | captacao_lista.html |
| `/captacao/<int:pk>/` | `captacao_detalhe` | `captacao.captacao_detalhe` | "candidaturas" · pode_ver | captacao_detalhe.html |
| `/avisos/<int:pk>/enviado/` | `aviso_enviado` | `captacao.aviso_enviado` | "candidaturas" POST · pode_ver | — (redireciona/arquivo) |
| `/dias-sem-estagio/` | `dias_sem_estagio` | `orientador.dias_sem_estagio` | "feriados" | dias_sem_estagio.html |
| `/dias-sem-estagio/importar/` | `importar_feriados` | `orientador.importar_feriados` | "feriados" | importar_feriados.html |
| `/documentos/` | `documentos_gerais` | `orientador.documentos_gerais` | "arquivos" | documentos.html |
| `/documentos/pasta/` | `pasta_geral` | `pasta.pasta_geral` | "painel" | pasta_geral.html |
| `/documentos/tipos/` | `tipos_documento` | `pasta.tipos_documento` | "arquivos" | tipos_documento.html |
| `/documentos/tipos/<int:pk>/` | `tipo_documento_editar` | `pasta.tipos_documento` | "arquivos" | tipos_documento.html |
| `/estagios/<int:pk>/pasta/<int:tipo_pk>/papel/` | `entregue_em_papel` | `pasta.entregue_em_papel` | "painel" POST · eh_orientador_do, pegar_estagio | — (redireciona/arquivo) |
| `/documentos/pasta/papel/` | `entregue_em_papel_lote` | `pasta.entregue_em_papel_lote` | "painel" POST · eh_orientador_do | — (redireciona/arquivo) |
| `/supervisao/<int:pk>/pedir-confirmacao/` | `pedir_confirmacao` | `confirmacao.pedir_confirmacao` | "painel" POST | — (redireciona/arquivo) |
| `/mapa/` | `mapa_estagios` | `mapa.mapa_estagios` | "painel" | mapa.html |
| `/agenda/roteiro/` | `roteiro` | `roteiro.roteiro` | "agenda" | roteiro.html |
| `/agenda/roteiro/agendar/` | `agendamento_rapido` | `roteiro.agendamento_rapido` | "agenda" POST | agenda_rapida.html |
| `/agenda/ficha/<int:pk>/` | `ficha_estagio` | `agenda.ficha_estagio` | login · is_superuser; usa "agenda" | _ficha_estagio.html |

### Administrador (is_superuser)

| URL | Nome | View | Acesso (decorador · checagem no código) | Template |
|---|---|---|---|---|
| `/opinioes/` | `opinioes` | `opinioes.opinioes` | login · is_superuser | opinioes.html |
| `/opinioes/<int:pk>/marcar/` | `marcar_opiniao` | `opinioes.marcar_opiniao` | login POST · is_superuser | — (redireciona/arquivo) |
| `/sugestoes/anexos/<int:pk>/` | `anexo_sugestao` | `novidades.anexo_sugestao` | aberta · is_superuser | — (redireciona/arquivo) |
| `/configuracoes/` | `configuracoes` | `orientador.configuracoes` | "painel" · is_superuser | configuracoes.html |
| `/configuracoes/emails/` | `modelos_email` | `modelos_email.lista` | "painel" · is_superuser | modelos_email.html |
| `/configuracoes/emails/<str:tipo>/` | `modelo_email` | `modelos_email.editar` | "painel" · is_superuser | modelo_email.html |
| `/sistema/erros/` | `erros_sistema` | `sistema.erros` | login · is_superuser | erros_sistema.html |
| `/sistema/erros/limpar/` | `marcar_erro_lote` | `sistema.marcar_erro` | login POST · is_superuser | — (redireciona/arquivo) |
| `/sistema/erros/<int:pk>/` | `marcar_erro` | `sistema.marcar_erro` | login POST · is_superuser | — (redireciona/arquivo) |
| `/sistema/acoes/` | `registro_acoes` | `sistema.acoes` | login · is_superuser | registro_acoes.html |

### Fora do `urls.py` do app

| URL | O que é | Acesso |
|---|---|---|
| `/admin/` | Django Admin (`core/admin.py`) | `is_staff`; o login passa pela tela normal (`_login_do_admin`), com limite de tentativas e 2FA |
| `/saude/` | healthcheck do container | aberta, responde `ok` |
| `/nao-publico/…` | `MEDIA_URL`; **não é servida**: todo anexo passa por uma view que confere a permissão | — |
