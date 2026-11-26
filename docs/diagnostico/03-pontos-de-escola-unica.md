# 03 — Tudo o que assume escola única

Levantado em 25/11/2026. Para cada ponto: onde está, o que assume e o que muda com várias escolas (Etapa 1).
O diagnóstico do prompt (seção 3) foi **confirmado**; os itens marcados com ➕ são achados novos.

## 1. Configuração, caches e registro único

| Onde | O que assume | Com várias escolas |
|---|---|---|
| `Configuracao.save()` força `pk = 1`; `Configuracao.atual()` faz `get_or_create(pk=1)` (`core/models.py`) | uma configuração para o sistema | `Configuracao` 1:1 com `Escola`; `atual()` resolve pela escola da requisição (contextvar já existente) |
| `Configuracao.atual()` é chamada em **28 arquivos** (cerca de 60 linhas fora dos testes): views, serviços, e-mails, termos, tarefas, `popular_demo` | idem | o contextvar `CACHE_REQUISICAO` vira também "escola atual". Fora de requisição (tarefas, comandos) a escola precisa ser passada explicitamente |
| ➕ `Configuracao.objects.filter(pk=1)` direto, para "reservar" o envio de uma tarefa entre processos: `core/acompanhamento.py:248`, `core/feedback.py:70`, `core/avaliacoes.py:193`, `core/management/commands/enviar_resumo_semanal.py:41`; `confirmacao.py` usa `filter(pk=config.pk)` | carimbos de envio (`resumo_enviado_em`, `lembrete_feedback_em`, `lembrete_avaliacoes_em`, `confirmacao_enviada_em`, `resumo_mensal_enviado_em`) são do sistema | carimbo **por escola** (na `Configuracao` de cada escola, ou numa tabela `ExecucaoTarefa(escola, tarefa, quando)`) |
| `CACHE_REQUISICAO` (contextvar, `core/models.py`) | guarda só a configuração | ponto natural para guardar a escola atual da requisição |
| Não há uso de `django.core.cache`, `lru_cache` nem cache entre requisições | — | nada a migrar; atenção se a Etapa 1 criar cache de escola por domínio |

## 2. Unicidades globais

| Campo | Hoje | Proposta |
|---|---|---|
| `Curso.nome` | `unique=True` | `UniqueConstraint(escola, nome)` |
| `ModeloEmail.tipo` | `unique=True` | `(escola, tipo)` com `escola` nula = padrão da plataforma |
| ➕ `Configuracao` | `pk = 1` | `OneToOne(Escola)` |
| ➕ `Candidatura.protocolo` | único global, 6 caracteres de 32 símbolos | pode continuar global (é um identificador); a busca pelo protocolo precisa filtrar a escola |
| ➕ `ImpressaoFrequencia.codigo` | único global, 8 caracteres | idem: global, mas a consulta pelo código filtra a escola |
| ➕ `Usuario.username` | único global, gerado como `primeiro.ultimo` + número | continua global (conta única por pessoa). Com mais escolas, os sufixos crescem; avaliar login por CPF ou e-mail na Etapa 1 |
| ➕ `ErroSistema.assinatura` | único global | global da plataforma; para a gestão da escola ver só os seus, guardar `escola` (nula quando não houver) e incluir a escola na assinatura |
| `InscricaoPush.endpoint`, `SessaoAparelho.chave`, `LinkConfirmacao.resumo` | únicos globais | corretos como estão (são do aparelho ou do link) |
| `Turma (curso, nome, ano_ingresso)`, `Escala`, `Registro`, `Avaliacao`, `Feedback`, `DiaPlanejado`, `VagaCandidatura`, `VinculoResponsavel` | compostos com algo que já é da escola | continuam corretos se `Curso`/`Estagio` forem da escola |
| ➕ Unicidades "na mão" | importação acha curso pelo nome (todos os cursos), concedente por CNPJ + nome (todas), supervisor pelo nome (todos), estagiário pelo CPF (qualquer papel) ou pelo nome | toda busca da importação passa a ser `da_escola(escola)`; CPF continua global (pessoa única), mas o vínculo é por escola |

## 3. Comandos e tarefas periódicas

Não há cron. O `ResumoSemanalMiddleware` (`core/middleware.py`) roda, a cada 10 minutos por processo, dentro de uma
requisição qualquer:

| Tarefa | Arquivo | O que assume |
|---|---|---|
| resumo semanal (segunda, 6h) | `core/acompanhamento.py` | uma configuração, um carimbo, `TIME_ZONE` global |
| lembrete de feedback (dia 20) | `core/feedback.py` | idem |
| lembrete de avaliações (dia 20) | `core/avaliacoes.py` | idem; texto cita o SICE |
| lembrete de fim de expediente | `core/lembretes.py` | percorre **todos** os estágios ativos do sistema com a configuração única |
| "Confirmar todas" por e-mail | `core/confirmacao.py` | dia da semana único; percorre todos os supervisores |
| resumo do mês do supervisor | `core/confirmacao.py` | idem; link com `SITE_URL` global |
| limpeza da auditoria (365 dias) e das sessões | `core/auditoria.py`, `core/sessoes.py` | regras globais (podem continuar globais) |
| comando `enviar_resumo_semanal` | `core/management/commands/` | `Configuracao.objects.filter(pk=1)` |
| comando `criar_orientador` (chamado no `entrypoint.sh` com `ADMIN_NOME`) | idem | o "primeiro administrador" é do sistema inteiro |
| comando `popular_demo` | idem | preenche a configuração única com "EEEP Escola de Demonstração", Fortaleza |

Com várias escolas, cada tarefa percorre as escolas ativas e usa a configuração (e o fuso) de cada uma. Uma pessoa
com vínculo em duas escolas pode receber dois resumos ou um resumo agrupado: **decisão pendente**.

## 4. E-mails, uploads, push, PWA, tokens e links assinados

| Ponto | Onde | O que assume | Com várias escolas |
|---|---|---|---|
| Remetente | `DEFAULT_FROM_EMAIL` (`EMAIL_REMETENTE`) | um remetente | pode continuar da plataforma, com o nome da escola no assunto/assinatura; "responder para" da escola |
| Variável `{escola}` dos e-mails | `core/emails.py:153` | `Configuracao.atual().nome_escola` | escola do destinatário **no contexto do e-mail** (passar a escola explicitamente) |
| `SITE_URL` nos links | `settings.py`, `confirmacao.py`, `alertas.py`, `emails.py` | um domínio | um domínio da plataforma basta (escola pelo caminho ou pela conta); subdomínio por escola é opção do ADR |
| Textos de e-mail editáveis | `ModeloEmail` | um texto por tipo | padrão global + versão por escola |
| Uploads | `MEDIA_ROOT = /data/anexos` (ver mapa de dados) | sem separação | prefixo `escolas/<id>/…` para arquivos novos; os antigos ficam onde estão e são associados pela linha do banco. Todo download confere a escola |
| `Documento` | `caminho_anexo` usa o **nome original** do arquivo | — | ➕ trocar por nome aleatório (o nome original já fica em `nome_original`) |
| Brasão da folha | `Configuracao.logo_folha` (`config/`) e `static/img/brasao-ceara-seduc.png` | um brasão; padrão do Ceará | da escola, senão da rede, senão nenhum |
| Push (VAPID) | `/data/vapid_privada.pem`, `core/push.py` | uma chave, título `NOME_SISTEMA` | uma chave da plataforma está certa (mesma origem). O título pode trazer a escola |
| `InscricaoPush` / `Notificacao` | `core/models.py` | sem escola | `Notificacao.escola` (nula = da plataforma) para o sino e o push saberem a origem; a inscrição continua por pessoa |
| PWA | `core/views/pwa.py` | nome `NOME_SISTEMA`, ícones fixos | um app da plataforma; nome da escola dentro do app |
| Código de primeiro acesso | `core/seguranca.py` (HMAC por usuário) | — | por pessoa; continua global |
| Confirmação de e-mail | `core/emails.py` (`signing`, sal `core.confirmar_email`) | — | por pessoa; continua global |
| "Esqueci minha senha" | Django (`PASSWORD_RESET_TIMEOUT`) | — | por pessoa; continua global |
| QR do check-in | `core/qrcheckin.py` (`signing`, guarda só o id do supervisor) | o supervisor tem estagiários de uma escola | ➕ o token precisa levar a escola (o supervisor pode atuar em duas) e a view precisa conferir que o estágio é dessa escola |
| Link "Confirmar todas" | `LinkConfirmacao` (`registros` em JSON) | os registros do supervisor | ➕ gravar a escola no link e filtrar os registros por ela |
| Agenda iCal | `Usuario.token_agenda`, `agenda_ics` | a agenda da pessoa | decidir se o calendário junta as escolas (com o nome de cada uma no evento) ou se há um link por vínculo |
| Folha de frequência (código no rodapé) | `ImpressaoFrequencia.codigo` | — | consulta filtra a escola |
| Captação pública | `/seja-concedente/` | uma captação, da `Configuracao` | ➕ a página pública precisa saber de qual escola é: `/seja-concedente/<slug-da-escola>/`, com a rota atual redirecionando para a escola atual |
| Candidatura → "minha candidatura" | conta do supervisor | — | a conta pode ter candidaturas em escolas diferentes |
| Busca global | `core/views/roteiro.py` (`buscar`) | `estagios_visiveis`, concedentes e contas de todo o sistema | busca com escopo da escola atual |
| Escopo de dados | `estagios_visiveis` (`core/services.py`) para superusuário devolve **todos** os estágios | um administrador = toda a escola = todo o sistema | o administrador da escola vê a escola; só o administrador da plataforma vê tudo |
| `/admin/` (Django Admin) | `core/admin.py` | quem é `is_staff` vê todos os dados | restringir ao administrador da plataforma |

## 5. Textos fixos de SEDUC, SICE, CEPAE e Ceará

### No código e nos templates (vão para a escola ou para a rede na Etapa 1)

| Texto | Onde |
|---|---|
| "Secretaria da Educação do Ceará" | `settings.NOME_INSTITUICAO` (padrão), `docker-compose.yml`, `.env.example`; aparece na barra do governo (`templates/base.html`) e em `services._nome_escola()` |
| Cabeçalho "Coordenadoria de Educação Profissional / Célula de Estágio - CEPAE" | padrão de `Configuracao.cabecalho_folha` (`core/models.py:1483`) |
| Brasão "Governo do Ceará / SEDUC" | `static/img/brasao-ceara-seduc.png`, usado em `folha_frequencia.html`, `relatorio_turma.html`, `declaracao.html`; texto de ajuda em `core/models.py:1488` |
| "FREQUÊNCIA DE ESTÁGIO" e medidas da folha oficial CEPAE/SEDUC | `templates/core/folha_frequencia.html` |
| "mesmos campos do formulário da SEDUC" | `core/forms.py:558` (docstring) |
| "Os registros oficiais continuam no SICE." | `templates/registration/_login_lado.html` |
| "Avaliações (SICE)" no menu, telas de copiar para o SICE, "Abrir o SICE" | `context_processors.py`, `avaliacoes_*.html`, `avaliacao_copiar.html`, `acompanhamento_*.html`, `estagio_detalhe.html`, `core/avaliacoes.py`, `core/views/visitas.py`, `core/views/avaliacoes.py` |
| Listas de atividades práticas do SICE por curso | `core/sice.py`, criadas por sinal em `core/apps.py` |
| "Frequência Detalhada do SICE" | `core/services.py:954`, `estagio_detalhe.html` |
| "Feriados nacionais e do Ceará", "Data Magna do Ceará" | `core/services.py:459–469`, `dias_sem_estagio.html` |
| UF padrão "CE" | `DadosConcedente.uf`, `DiaSemEstagio.uf` (`core/models.py`) |
| Mapa centrado no Ceará | `static/js/mapa.js:129` |
| Fuso `America/Fortaleza` | `settings.TIME_ZONE`, `Dockerfile` (`TZ`) |
| "EEEP …" nos exemplos | `Configuracao.nome_escola` (help_text), `popular_demo` |
| "a SEDUC" como fonte de calendário | `importar_feriados.html` (só texto de ajuda) |
| Exemplos da importação ("Secretaria da Educação", Fortaleza, CE) | `core/importacao.py:512–514` (modelo CSV com dados fictícios) |

Também há menções em `core/novidades.py` (histórico de versões: é histórico, pode ficar) e em `static/css/app.css`
(nomes de classes como `.lista-sice`; não aparecem ao usuário).

### Proposta de destino

- **Rede** (`RedeEnsino`): nome da secretaria, sistema oficial ("SICE"), URL do sistema oficial, listas de atividades
  e perguntas padrão do sistema oficial, brasão e cabeçalho padrão da folha, UF e fuso padrão, feriados estaduais.
- **Escola**: nome, município, UF, fuso (se diferente da rede), brasão próprio, cabeçalho próprio, contato de
  privacidade, texto da captação.
- **Código**: rótulos genéricos ("sistema oficial", "Avaliações para {{ sistema_oficial }}"). Com a rede CE/SEDUC e
  a escola atual cadastradas assim, a aparência continua igual.
