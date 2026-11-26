# Dicionário de dados — rascunho (Etapa 0)

> **Situação:** rascunho para revisão. A versão final sai na Etapa 2. Partiu do Apêndice A do plano de 2027 e foi
> confrontado com `core/models.py` em 25/11/2026. Cada entidade diz se **já existe** (e com que nome), se é **nova** ou
> se é **campo a extrair**. As divergências com o código e com a ficha da SEDUC estão no fim.
>
> A ficha da SEDUC não foi aberta (é documento com dados reais ou, no mínimo, fora do código). Os campos da "ficha"
> citados aqui são os que o código diz copiar dela (`DadosConcedente`, "mesmos campos do formulário da SEDUC").
> **Conferir com um modelo em branco da ficha** é uma decisão pendente.

## Convenções

- **Classificação:** **P** público · **I** interno da escola · **D** dado pessoal · **S** dado pessoal sensível ou de
  menor de idade (acesso mínimo, auditado).
- **Obrig.:** S = obrigatório; N = opcional; C = condicional (explicado na validação).
- **Origem:** TCE · ficha da SEDUC · candidatura · importação · a própria pessoa · gestão · sistema.
- **Quem vê:** perfis do sistema. "Gestão" = orientador e coordenador, conforme as permissões e o escopo
  (orientador: os próprios estagiários; coordenador: os cursos que coordena).
- **Retenção:** "ano + N" = até N anos depois do fim do ano do estágio (`Configuracao.retencao_anos`, padrão 5), quando
  o encerramento do ano anonimiza. "Vínculo" = enquanto o vínculo estiver ativo.
- Códigos de coluna para a importação (Etapa 2): `snake_case`, iguais aos nomes abaixo quando possível.

## Ordem de dependência (importação)

Escola e configuração → Cursos → Turmas → Equipe escolar → Concedentes → Contatos e responsáveis da concedente →
Supervisores → Estudantes → Responsáveis legais → Estágios e escalas.

---

## RedeEnsino — nova (opcional)

Finalidade: o que é comum a várias escolas da mesma rede (secretaria, sistema oficial, brasão padrão).

| Campo | Tipo | Obrig. | Classif. | Validação / observação |
|---|---|---|---|---|
| `nome` | texto 160 | S | P | ex.: "Secretaria da Educação do Ceará" |
| `sigla` | texto 20 | N | P | ex.: "SEDUC" |
| `uf` | UF | S | P | lista de UFs |
| `sistema_oficial` | texto 40 | N | P | ex.: "SICE"; vazio = sem sistema oficial (os textos "copiar para o SICE" somem) |
| `sistema_oficial_url` | URL | N | P | hoje é `Configuracao.sice_url` |
| `brasao` | imagem | N | P | hoje é `static/img/brasao-ceara-seduc.png` |
| `cabecalho_folha` | texto | N | P | hoje é o padrão "Coordenadoria de Educação Profissional / CEPAE" |
| `fuso` | texto | S | P | padrão `America/Fortaleza` |

Chave natural: `nome + uf`. Quem vê: administrador da plataforma (edita); todos (leem o que aparece nas telas).
Origem: plataforma. Retenção: permanente.

## Escola — nova

Finalidade: raiz do isolamento. Hoje é implícita (`Configuracao.nome_escola`, `municipio_escola`).

| Campo | Tipo | Obrig. | Classif. | Validação / observação |
|---|---|---|---|---|
| `rede` | FK RedeEnsino | N | P | |
| `nome` | texto 160 | S | P | hoje `Configuracao.nome_escola` |
| `codigo_inep` | 8 dígitos | S | P | único; 8 dígitos |
| `cnpj` | CNPJ | N | P | dígitos verificadores |
| `municipio`, `uf` | texto, UF | S | P | hoje `municipio_escola`; UF não existe hoje |
| `fuso` | texto | N | P | vazio = da rede |
| `endereco`, `telefone`, `email` | texto | N | P | |
| `encarregado_dados` | texto | N | P | nome e contato; hoje `Configuracao.contato_privacidade` |
| `slug` | slug | S | P | único; usado na URL pública da captação |
| `situacao` | escolha | S | I | implantação, piloto, ativa, inativa |
| `logotipo`, `brasao`, `cabecalho_folha` | imagem, imagem, texto | N | P | hoje `Configuracao.logo_folha`, `cabecalho_folha`; vazio = da rede |

Chave natural: `codigo_inep`. Quem vê: administrador da plataforma (edita tudo), administrador da escola (edita
identidade e contatos). Origem: implantação. Retenção: permanente (encerramento da escola: Etapa 7).

## Configuracao — existe (passa a ser 1:1 com a escola)

Mantém todos os campos atuais (localização no check-in, avisos por e-mail, resumo semanal, avaliações, período de
testes, tema escuro, retenção, feedback mensal, lembrete de expediente, "Confirmar todas", resumo mensal, 2FA da
gestão, atestados pelo supervisor, folha, captação, currículos e banco de talentos). Mudanças:

- `nome_escola`, `municipio_escola`, `logo_folha`, `cabecalho_folha`, `contato_privacidade` → migram para `Escola`
  (a configuração lê de lá; os campos antigos ficam até a migration de limpeza, depois do piloto);
- `sice_url` → `RedeEnsino.sistema_oficial_url` (com valor da escola sobrepondo, se preciso);
- `ano_referencia` → `AnoLetivo` (o campo continua como compatibilidade em 2027);
- carimbos das tarefas (`*_enviado_em`, `lembrete_*_em`) continuam aqui, agora por escola.

Classificação: I. Quem vê: administrador da escola. Origem: gestão. Retenção: permanente.

## AnoLetivo — nova

| Campo | Tipo | Obrig. | Classif. | Observação |
|---|---|---|---|---|
| `escola` | FK | S | I | |
| `ano` | inteiro | S | I | |
| `inicio`, `fim` | data | N | I | |
| `referencia` | booleano | S | I | o ano que as listas mostram; um por escola |

Chave natural: `escola + ano`. Substitui `Configuracao.ano_referencia` e o cálculo `ano_estagio`/`ano_em_uso`.
**Avaliar na Etapa 1 se entra já ou depois do piloto** (decisão pendente): hoje o ano de referência resolve bem.

## Curso — existe

| Campo | Tipo | Obrig. | Classif. | Validação |
|---|---|---|---|---|
| `escola` | FK | S | P | **novo** |
| `nome` | texto 120 | S | P | hoje único global → único por escola |
| `eixo` | texto | N | P | **novo**, não existe hoje |
| `carga_horaria` | inteiro (h) | S | P | padrão 300 |
| `horas_por_dia_padrao` | decimal | S | P | padrão 4 |
| `na_captacao` | booleano | S | P | |

Chave natural: `escola + nome` (comparação sem acento e sem caixa, como `_chave` faz hoje). Quem vê: todos da escola.
Origem: gestão, importação. Retenção: permanente.

## Turma — existe

Campos atuais: `curso`, `nome`, `ano_ingresso`, `ano_estagio`, `ativa`. Chave natural: `curso + nome + ano_ingresso`
(já é constraint). Validação: `ano_estagio >= ano_ingresso`. A escola vem do curso. Classificação: I.

## Pessoa / Usuario — existe

Conta global, um login por pessoa.

| Campo | Tipo | Obrig. | Classif. | Origem | Observação |
|---|---|---|---|---|---|
| `nome_completo` | texto 150 | S | D | TCE, importação, a própria pessoa | normalizado (`normalizar_nome`) |
| `nome_social` | texto | N | D | a própria pessoa | **novo**; exibir no lugar do nome civil onde couber |
| `cpf` | CPF | C | D | TCE, importação | válido; **não é único hoje**. Proposta: único quando preenchido (exige limpeza de duplicatas antes) |
| `data_nascimento` | data | C | D / **S** se menor | TCE, importação | obrigatória para estudantes (primeiro acesso) |
| `email` | e-mail | N | D | a própria pessoa | confirmação por link |
| `telefone` | texto | N | D | importação, a própria pessoa | |
| `tem_whatsapp` | booleano | N | D | a própria pessoa | **novo**; não supor que todo celular tem WhatsApp |
| `foto` | imagem | N | D | a própria pessoa | |
| `matricula` | texto | N | D | importação | **sai daqui** para `Estudante` (fica como compatibilidade) |
| `papel` | escolha | S | I | sistema | em 2027 é o papel principal, preenchido a partir de `VinculoEscola` |
| currículo, apresentação, habilidades | arquivo, texto | N | D | a própria pessoa | banco de talentos, só com `perfil_visivel` |

Chave natural: CPF; sem CPF, nome completo + data de nascimento (com alerta). Endereço da pessoa: **não guardar**
(sem finalidade clara). Quem vê: a própria pessoa; gestão da escola (dados de contato); supervisor (nome e contato
dos seus estagiários); CPF só na ficha da gestão, nunca em listagens. Retenção: ano + N para estudantes; vínculo + N
para os demais (decisão pendente).

## VinculoEscola — nova

| Campo | Tipo | Obrig. | Classif. |
|---|---|---|---|
| `usuario`, `escola` | FK | S | I |
| `papel` | orientador, coordenador, supervisor, estagiário, responsável legal, contato de concedente, administrador da escola | S | I |
| `ativo`, `inicio`, `fim` | booleano, datas | S/N | I |

Chave natural: `usuario + escola + papel`. Permite vários papéis e várias escolas por pessoa. Os coordenadores levam
os cursos coordenados (hoje M2M `Usuario.cursos_coordenados`, que precisa ganhar a escola via curso).

## Estudante (matrícula) — nova

| Campo | Tipo | Obrig. | Classif. |
|---|---|---|---|
| `usuario`, `escola` | FK | S | D |
| `matricula` | texto | N | D |
| `turma` | FK | N | I |
| `situacao` | ativo, concluinte, transferido, desligado | S | I |

Chave natural: `escola + matricula`; sem matrícula, o CPF do usuário. Base para a integração futura com o portal
EEEP. **Pode ficar para depois do piloto** (decisão pendente): em 2027, `Estagio.turma` + `Usuario.matricula` cobrem
o uso atual.

## ResponsavelLegal — existe como `VinculoResponsavel`

| Campo | Hoje | Proposta |
|---|---|---|
| `estagiario`, `responsavel` | existem | manter |
| `parentesco` | existe (S) | manter |
| `origem` | TCE, PEDIDO | manter |
| `tipo` | — | **novo**: responsável legal ou só contato |
| `recebe_avisos` | — | **novo** (hoje todos recebem) |
| `criado_em`, `encerrado_em` (+ por quem) | existem | manter; `inicio` = `criado_em` |

Chave natural: `estudante + CPF do responsável`. Regras atuais mantidas: responsável de quem começou o estágio com 18
anos ou mais gera alerta; irmãos compartilham o mesmo responsável. Classificação: S (relação com menor). Quem vê:
gestão da escola com "estagiarios"/"contas"; o próprio responsável. Origem: TCE, pedido. Retenção: vínculo + N.

## Concedente — existe como `LocalEstagio` (+ `DadosConcedente`)

| Campo | Tipo | Obrig. | Classif. | Origem | Observação |
|---|---|---|---|---|---|
| `escola` | FK | S | I | sistema | **novo** |
| `tipo_concedente` | PJ, PL | S | P | ficha | |
| `razao_social` | texto 200 | N | P | ficha | |
| `nome` | texto 160 | S | P | ficha | nome fantasia ou unidade; sai na folha |
| `cnpj` | CNPJ ou CPF | N | P (CNPJ) / **D** (CPF de profissional liberal) | ficha | dígitos verificadores; **não exibir CPF em listagens** |
| `matriz_filial` | escolha | N | P | ficha | |
| `tipo_instituicao` | pública, privada | N | P | ficha | |
| `atividade` | texto | N | P | ficha | |
| endereço (`endereco`, `numero`, `bairro`, `complemento`, `cidade`, `uf`, `cep`) | texto | N | P | ficha | `uf` padrão "CE" → padrão da escola |
| `telefone` | texto | N | P | ficha | telefone institucional (**não** supor WhatsApp) |
| `latitude`, `longitude`, `raio_checkin` | decimal, inteiro | N | I | gestão | ponto do check-in |
| `link_mapa`, `observacoes` | URL, texto | N | I | gestão | |
| `ativa` | booleano | S | I | gestão | |

Chave natural: `escola + CNPJ/CPF + nome da unidade` (vários órgãos usam o mesmo CNPJ). Quem vê: gestão (tudo);
supervisor e responsável da concedente (os dados da própria concedente). Cadastro compartilhado entre escolas: depois
do piloto.

## RepresentanteLegal — campos da concedente hoje

`representante_nome`, `representante_email`, `representante_cpf` (D), `representante_documento` (D). Proposta:
**manter como campos da concedente em 2027** (uma concedente tem um representante na ficha; extrair só traria
migração sem ganho para o piloto). Reavaliar com ADR se aparecer concedente com vários representantes.

## ContatoConcedente — nova

| Campo | Tipo | Obrig. | Classif. | Observação |
|---|---|---|---|---|
| `concedente` | FK | S | I | |
| `nome`, `cargo` | texto | S/N | D | |
| `telefone`, `tem_whatsapp`, `email` | texto, booleano, e-mail | C | D | ao menos telefone ou e-mail |
| `finalidades` | relacionamento com a escola, RH, financeiro, outro | S | I | múltipla escolha |
| `principal` | booleano | S | I | um principal por concedente |
| `usuario` | FK opcional | N | D | quando o contato também é supervisor ou responsável |
| `ativo`, `origem`, datas | — | S | I | origem: candidatura, gestão, importação, sugestão confirmada |

Chave natural: `concedente + telefone` ou `concedente + e-mail`. Na aprovação da candidatura, `contato_*` vira um
`ContatoConcedente`. Destinatário da renovação.

## ResponsavelConcedente — existe como `Usuario.concedentes_geridas` (M2M)

Gerencia a equipe e as substituições. Manter. Com várias escolas, a concedente já é da escola, então o vínculo herda
o escopo.

## Supervisor — existe como `Usuario` (papel SUPERVISOR) + `Usuario.concedentes` (M2M)

| Campo | Hoje | Proposta |
|---|---|---|
| `concedentes` | M2M | manter |
| `cargo` | existe | manter |
| `formacao_experiencia` | — | **novo**: formação ou experiência na área (art. 9º, III, da Lei 11.788) |

Chave natural: CPF; sem CPF, e-mail + concedente. **Hoje a importação acha o supervisor só pelo nome** (risco de
juntar homônimos). Alerta acima de 10 estagiários simultâneos.

## EquipeEscolar — `Usuario` (ORIENTADOR, COORDENADOR) + `cursos_coordenados`

Vira `VinculoEscola` com papel orientador ou coordenador. Chave natural: CPF ou e-mail. Importável (Etapa 2). Hoje não
há importação: as contas são criadas uma a uma (`criar_orientador`, `criar_coordenador`).

## Estagio — existe

| Campo | Tipo | Obrig. | Classif. | Origem | Observação |
|---|---|---|---|---|---|
| `escola` | FK | S | I | sistema | **novo** (redundante com o curso, mas simplifica escopo e índices) |
| `estagiario`, `orientador`, `supervisor` | FK Usuario | S/S/N | D | TCE, importação | supervisor só troca por outro (histórico em `TrocaSupervisor`) |
| `curso`, `turma` | FK | S/N | I | | turma do mesmo curso |
| `local` (concedente) | FK | N | I | TCE | supervisor precisa estar vinculado à concedente |
| `setor` | texto | N | I | TCE | |
| `data_inicio`, `data_fim` | data | S/N | I | TCE | |
| `carga_horaria`, `horas_anteriores`, `acompanhamento_desde` | — | N | I | TCE, importação | |
| `numero_tce`, `data_tce` | texto, data | N | I | TCE | **novo** |
| `apolice_seguro` | texto | N | I | TCE | **novo**, se a ficha exigir (decisão pendente) |
| `ativo` | booleano | S | I | gestão | |
| `observacoes_orientador` | texto | N | D | gestão | só orientador/gestão |

Chave natural: `estudante + concedente + início`. Escalas, registros e justificativas seguem ligados ao estágio.
Retenção: ano + N.

## Escala — existe

`estagio`, `vigente_desde`, `dias`, horários, `horas_por_dia`. Chave natural: `estagio + vigente_desde` (já é
constraint). Classificação: I.

## Candidatura e VagaCandidatura — existem

Adicionar `escola`. Chave natural: `escola + protocolo`. Na aprovação, gera ou completa a concedente (por CNPJ e nome,
como hoje) **e cria o `ContatoConcedente`**. Contato e supervisor proposto: D. `ip`: D (retenção curta, decisão
pendente).

## RenovacaoParceria e ContatoRenovacao — novas (Etapa 4)

Como no Apêndice A. `RenovacaoParceria`: `escola + concedente + ano_letivo` único. `ContatoRenovacao`: histórico,
auditado; abrir o WhatsApp não conta como contato.

## LoteImportacao — nova (Etapa 2)

`escola`, `entidade`, `modo`, `usuario`, `data`, `hash_arquivo`, `versao_modelo`, contagens, resultado. O arquivo não é
guardado. Classificação: I.

## Atestado e justificativa — existe como `Justificativa`

**S** (saúde). Acesso mínimo, como hoje: o estudante, quem decide (escola e, se a configuração deixar, o supervisor).
Retenção: ano + N, com o arquivo apagado na anonimização.

## Demais entidades existentes (sem mudança de conceito)

Herdam a escola pelo estágio: `Registro` (localização = D), `HistoricoRegistro`, `DiaPlanejado`, `TrocaSupervisor`,
`Mensagem`, `Avaliacao`, `AcompanhamentoVisita`, `Feedback`, `ImpressaoFrequencia`.
Precisam de `escola` própria: `DiaSemEstagio` (feriado "TODOS" passa a ser da escola ou da rede), `Agendamento`,
`Comunicado`, `TipoDocumento`, `PerguntaAvaliacao` (padrão da rede + versão da escola), `Documento` (os gerais não têm
estágio), `FolhaEnviada`, `AvisoExterno`, `Encerramento`, `Anonimizacao`, `ModeloEmail` (nula = padrão), `Sugestao`,
`ErroSistema` e `RegistroAcao` (nulas = plataforma), `Notificacao` (nula = plataforma), `LinkConfirmacao`.
Continuam globais (são da pessoa ou do aparelho): `InscricaoPush`, `SessaoAparelho`, `TentativaLogin`.

---

## Divergências registradas

| # | Apêndice A | Código hoje | Proposta |
|---|---|---|---|
| 1 | `Curso.eixo` | não existe | criar (opcional) |
| 2 | `Pessoa.nome_social`, `tem_whatsapp` | não existem | criar |
| 3 | CPF como chave natural | CPF não é único nem no banco nem nos formulários | relatório de duplicatas antes de qualquer constraint |
| 4 | `Estudante` (matrícula, situação) | `Usuario.matricula` solto; sem situação | criar na Etapa 1 ou depois do piloto (decisão pendente) |
| 5 | `AnoLetivo` | `Configuracao.ano_referencia` + `Turma.ano_estagio` | idem |
| 6 | `VinculoResponsavel.tipo`, `recebe_avisos` | não existem | criar |
| 7 | `Supervisor.formacao_experiencia` | só `cargo` | criar |
| 8 | `Estagio.numero_tce`, `data_tce`, `apolice_seguro` | não existem | criar (apólice só se a ficha exigir) |
| 9 | `ContatoConcedente` | não existe; contato da candidatura se perde | criar (Etapa 2/4) |
| 10 | Supervisor por CPF | importação usa só o nome | corrigir na central de importação |
| 11 | `Escola.encarregado_dados` | `Configuracao.contato_privacidade` | mover |
| 12 | Brasão e cabeçalho da rede | fixos no `static/` e no default do campo | `RedeEnsino` |
| 13 | Ficha da SEDUC | não confrontada com o original | conferir com um modelo em branco (decisão pendente) |
