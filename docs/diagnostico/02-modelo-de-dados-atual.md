# 02 — Mapa do modelo de dados atual

Levantado de `core/models.py` (41 modelos, um único app `core`, 45 migrations até `0045_responsaveis_legais`).
Classificação dos campos: **P** público · **I** interno da escola · **D** dado pessoal · **S** dado pessoal sensível ou
de menor de idade.

## Visão geral das relações

```text
Configuracao (registro único, pk=1)

Curso ──< Turma
  │         │
  │         └──< FolhaEnviada >──< Estagio
  ├──< Estagio >── Usuario (estagiario, orientador, supervisor)
  │       │  └── LocalEstagio (local, opcional)
  │       ├──< Escala, Registro ──< HistoricoRegistro, DiaPlanejado, Justificativa
  │       ├──< Mensagem, Documento, Avaliacao, Feedback, AcompanhamentoVisita, ImpressaoFrequencia, TrocaSupervisor
  │       └──< (M2M) Agendamento
  ├──< TipoDocumento ──< Documento
  ├──< PerguntaAvaliacao (só a prática é por curso)
  ├──< DiaSemEstagio (curso opcional)
  └──< VagaCandidatura >── Candidatura ──> LocalEstagio (depois de aprovada)
                                 └──< AvisoExterno

LocalEstagio (herda DadosConcedente)
  ├── M2M Usuario.concedentes          (supervisores)
  ├── M2M Usuario.concedentes_geridas  (responsáveis pela concedente)
  ├──< Substituicao (titular, substituto)
  └──< DiaSemEstagio (recessos da concedente)

Usuario ──< VinculoResponsavel >── Usuario (estagiário ↔ responsável legal)
Usuario ──< Notificacao, InscricaoPush, SessaoAparelho, LinkConfirmacao, Comunicado (M2M destinatários)
Usuario ── M2M Curso (cursos_coordenados)

Sem chave para nada: ModeloEmail, ErroSistema, RegistroAcao (usuario opcional), TentativaLogin, Encerramento,
Anonimizacao, Sugestao ──< AnexoSugestao
```

## Entidades

### Pessoas e acesso

| Modelo | Finalidade | Relações | Campos pessoais |
|---|---|---|---|
| `Usuario` (AbstractUser) | conta de todos os perfis; `papel` único | M2M `concedentes`, `concedentes_geridas`, `cursos_coordenados`; `criado_por` | `nome_completo` D, `cpf` D, `data_nascimento` D (**S** se menor), `telefone` D, `email` D, `matricula` D, `foto` D, `curriculo` D, `apresentacao`/`habilidades` D, `token_agenda` (segredo), `totp_segredo` (segredo, texto claro), `codigo_acesso` (HMAC), `codigos_recuperacao` (HMAC) |
| `VinculoResponsavel` | responsável legal ↔ estudante | `estagiario`, `responsavel` (ambos `Usuario`) | `parentesco` S (revela relação familiar de menor) |
| `SessaoAparelho` | aparelhos conectados | `usuario` | `ip` D, `aparelho` D |
| `InscricaoPush` | celular com push | `usuario`; `endpoint` único global | `endpoint`/chaves (identificador do aparelho) D |
| `TentativaLogin` | limite de tentativas | — | `username` D, `ip` D (apagadas após um dia) |
| `LinkConfirmacao` | "Confirmar todas" do supervisor | `supervisor`, `criado_por` | — (guarda só o SHA-256 do código) |

### Escola, cursos e calendário

| Modelo | Finalidade | Relações | Observações |
|---|---|---|---|
| `Configuracao` | configurações gerais **da única escola** | — | `save()` força `pk=1`; `atual()` faz `get_or_create(pk=1)`. Guarda nome e município da escola, cabeçalho e brasão da folha, ano de referência, regras e os carimbos das tarefas periódicas (`resumo_enviado_em` etc.) |
| `Curso` | curso técnico | — | `nome` **único no sistema**; carga horária; aparece na captação |
| `Turma` | turma por ano de ingresso | `curso` | único `(curso, nome, ano_ingresso)` |
| `DiaSemEstagio` | feriados, recessos e eventos | `orientador`, `curso`?, `concedente`? | abrangência ESCOLA/MUNICIPIO/TODOS/CONCEDENTE; "TODOS" vale para o sistema inteiro; `uf` padrão "CE" |
| `Encerramento` | encerramento do ano letivo | `feito_por` | `resumo` JSON com ids alterados |
| `Anonimizacao` | registro da anonimização (sem dados) | `feita_por` | — |

### Concedentes e captação

| Modelo | Finalidade | Relações | Campos pessoais |
|---|---|---|---|
| `DadosConcedente` (abstrato) | campos da ficha da SEDUC | — | `cnpj` (CPF quando profissional liberal: **D**), `telefone` I, `representante_nome` D, `representante_email` D, `representante_cpf` D, `representante_documento` D |
| `LocalEstagio` | concedente | supervisores e responsáveis (M2M em `Usuario`), recessos, substituições | herda os acima; latitude/longitude/raio do check-in (I) |
| `Candidatura` | cadastro pela página pública | `conta`, `cadastrada_por`, `analisado_por`, `local` | herda os de `DadosConcedente`; `contato_nome/cargo/email/telefone` D, `contato_whatsapp`; `supervisor_nome/cargo/telefone/email` D; `ip` D; `protocolo` único global |
| `VagaCandidatura` | vagas por curso | `candidatura`, `curso` | — |
| `AvisoExterno` | mensagem enviada à mão (WhatsApp, e-mail, telefone) | `candidatura`? | `destinatario`, `email`, `telefone` D |
| `Substituicao` | quem confirma presenças no lugar do supervisor | `concedente`, `titular`, `substituto` | — |

### Estágio e acompanhamento

| Modelo | Finalidade | Relações | Campos pessoais |
|---|---|---|---|
| `Estagio` | estágio de um estudante | `estagiario`, `orientador`, `supervisor`, `curso`, `turma`?, `local`? | `setor` I, `observacoes_orientador` D (anotações sobre a pessoa) |
| `Escala` | dias e horários vigentes | `estagio`, `criado_por` | — |
| `Registro` | dia de estágio | `estagio`, `justificativa`? | `diario` D, `motivo` D/**S** (pode citar saúde), `geo_entrada`/`geo_saida` **D** (localização) |
| `HistoricoRegistro` | quem mudou o registro | `estagio`, `registro`?, `usuario` | `ip` D |
| `DiaPlanejado` | reposição planejada | `estagio` | — |
| `TrocaSupervisor` | histórico da troca | `estagio`, `anterior`, `novo`, `feita_por` | `motivo` I |
| `Justificativa` | atestado ou comprovante | `estagio`, `enviado_por`, `decidido_por` | **S** (saúde): `arquivo`, `motivo`, `parecer`, `tipo` |
| `Agendamento` | visita, conversa, reunião | `orientador`, `solicitante`, `local`?, M2M `estagios` | `detalhes`, `relato` D |
| `AcompanhamentoVisita` | avaliação da visita (SICE) | `estagio`, `agendamento`?, `autor` | `respostas`, `observacoes*`, `intervencoes*` D |
| `PerguntaAvaliacao` | perguntas das avaliações | `curso`? | — |
| `Avaliacao` | autoavaliação e avaliação do orientador | `estagio` | `respostas` D |
| `Feedback` | feedback mensal do supervisor | `estagio`, `autor` | notas e comentários D; `reservado` D (só a escola vê) |
| `TipoDocumento` | documento exigido na pasta | `curso`? | — |
| `Documento` | arquivo do estágio ou geral | `estagio`?, `curso`?, `orientador`, `enviado_por`, `tipo`? | `arquivo` D (TCE, relatórios); o caminho usa o **nome original do arquivo** (`caminho_anexo`) |
| `FolhaEnviada` | folha de frequência enviada | `turma`?, M2M `estagios`, `enviado_por` | `arquivo` D |
| `ImpressaoFrequencia` | quem abriu/imprimiu a folha | `estagio`, `usuario`, `folha_enviada`? | `ip`, `navegador` D; `codigo` único global |
| `Mensagem` | mural do estágio | `estagio`, `autor` | `texto` D |

### Comunicação e sistema

| Modelo | Finalidade | Relações | Campos pessoais |
|---|---|---|---|
| `Notificacao` | sino | `usuario` | `texto` pode citar o estudante (D) |
| `Comunicado` | aviso para turma, curso, concedente | `autor`, M2M `destinatarios` | — |
| `ModeloEmail` | texto editável dos e-mails | `atualizado_por` | `tipo` **único no sistema** |
| `Sugestao` / `AnexoSugestao` | "Sugestões e erros" e "Sua opinião" | `usuario`? | `nome`, `email`, `ip`, `navegador` D; anexos podem ter qualquer coisa |
| `ErroSistema` | erros 500 agrupados | `usuario`? | `detalhe` pode conter dados da requisição (D) |
| `RegistroAcao` | auditoria | `usuario`? | `quem`, `ip`, `aparelho` D (guardado por `GUARDAR_DIAS`) |

## Arquivos enviados (`MEDIA_ROOT = /data/anexos`)

| Origem | Caminho | Observação |
|---|---|---|
| `Usuario.foto` | `fotos/` | reprocessada, nome aleatório |
| `Usuario.curriculo` | `curriculos/` | nome dado pelo navegador |
| `Justificativa.arquivo` | `atestados/AAAA/MM/<aleatório>` | **S** |
| `Documento.arquivo` | `AAAA/MM/<nome original>` | nome original pode conter o nome do estudante |
| `TipoDocumento.modelo` | `modelos/` | |
| `FolhaEnviada.arquivo` | `folhas/AAAA-MM/<aleatório>` | |
| `AnexoSugestao.arquivo` | `sugestoes/AAAA/MM/<aleatório>` | |
| `Configuracao.logo_folha` | `config/` | um brasão para o sistema |
| chave VAPID | `/data/vapid_privada.pem` | uma chave para o sistema |

Nenhum caminho separa escolas. Todos os downloads passam por views com checagem de permissão (`MEDIA_URL` não é
servida).

## Pontos de atenção para o modelo de referência

- Não há `Escola`, `AnoLetivo`, `Estudante` (matrícula) nem `VinculoEscola`: a escola é implícita e a matrícula é um
  campo solto em `Usuario`.
- O estudante não tem "situação" (ativo, concluinte, transferido); o que existe é `Estagio.ativo` e a anonimização.
- O supervisor não tem formação ou experiência na área (a ficha da Lei 11.788 pede); só `cargo`.
- Contato da concedente não existe como entidade: há o telefone institucional, o representante legal, os supervisores
  e os responsáveis. O contato da `Candidatura` não é copiado para a concedente aprovada.
- `Estagio` não tem número/data do TCE nem apólice de seguro.
- O `VinculoResponsavel` não diz se a pessoa é responsável legal ou só contato, nem se recebe avisos.
- O CPF não é único no banco e os formulários só checam se ele é válido (`limpar_cpf`), não se já existe. Na
  importação de estagiários, a conta é reaproveitada pelo CPF (de qualquer papel) ou, sem CPF, pelo nome exato; os
  supervisores são identificados **só pelo nome** (`core/importacao.py`, `_supervisor`); as concedentes, por CNPJ +
  nome, ou só pelo nome quando não há CNPJ.
