# 06 — Decisões pendentes (para você)

> **Situação em 26/11/2026:** as decisões 1 a 22 foram tomadas por você ao fim da Etapa 0 (resumo na seção 3.1 do
> prompt e nas ADRs 0001 a 0004). Seguem abertas: a 20 (lista de rótulos da ficha da SEDUC e do TCE, em
> `docs/referencias/`) e a 24 (datas da captação de 2027). As decisões novas da Etapa 1 estão no relatório da etapa.

Nenhuma destas foi tomada pelo agente. Cada uma tem uma recomendação, mas a decisão é sua.

## Urgentes (antes da Etapa 1)

| # | Decisão | Recomendação |
|---|---|---|
| 1 | O `data/db.sqlite3` versionado no Git é cópia da produção? | conferir você mesmo (o agente não abre o arquivo). Se for, seguir o item 4 do [00](00-dados-pessoais-no-git.md): trocar `SECRET_KEY`, refazer 2FA, novos tokens da agenda |
| 2 | Reescrever o histórico do Git para apagar banco, TCEs, CSV e PDF (`git filter-repo` + *force push* + pedido de limpeza ao GitHub) | sim, depois de confirmar que o repositório é privado e de avisar quem tem clone. É irreversível |
| 3 | Autorizar a branch de correção a partir da `main` que para de versionar esses arquivos (commit e merge na `main`) | sim, o quanto antes; a regra do projeto exige seu pedido explícito para mexer na `main` |
| 4 | Comunicar o caso como incidente de segurança (LGPD, art. 48) | decisão do controlador (escola/SEDUC) com o encarregado de dados |
| 5 | Criar a branch `desenvolvimento` (hoje só existe a `main`) e o recurso de homologação no Coolify | criar `desenvolvimento` a partir da `main` depois do item 3 |

## Arquitetura (Etapa 1)

| # | Decisão | Recomendação |
|---|---|---|
| 6 | Aprovar o [ADR 0001](../decisoes/0001-arquitetura-multiescola.md): banco compartilhado com coluna `escola` | aprovar a opção (b) |
| 7 | Ordem dos deploys: PostgreSQL primeiro, multiescola depois | sim, em deploys separados, cada um com sua reversão |
| 8 | Endereço: um domínio da plataforma (escola pela conta e pelo caminho, ex.: `/seja-concedente/<escola>/`) ou subdomínio por escola | um domínio só em 2027 (cookies, push, PWA e Cloudflare continuam como estão) |
| 9 | `AnoLetivo` e `Estudante` (matrícula, situação) já na Etapa 1 ou depois do piloto | depois do piloto; em 2027 o ano de referência e `Usuario.matricula` resolvem |
| 10 | Pessoa com vínculo em duas escolas: um resumo semanal agrupado ou um por escola; agenda iCal única ou por vínculo | um resumo por escola; um calendário único com o nome da escola em cada evento |
| 11 | CPF único por pessoa (exige relatório e limpeza de duplicatas) e, talvez, login por CPF | relatório de duplicatas na Etapa 1; constraint só depois da limpeza; login por CPF fica para depois |
| 12 | Cifrar o `totp_segredo` em repouso (chave fora do banco) | sim, na Etapa 1 |
| 13 | Tarefas periódicas pelas *Scheduled Tasks* do Coolify (comandos) em vez do disparo pelo tráfego | sim para produção, mantendo o disparo pelo tráfego como reserva |
| 14 | Nome genérico para o "sistema oficial" nos textos (hoje "SICE") e a SEDUC/CE como primeira `RedeEnsino` | sim; a escola atual não muda de aparência |

## Banco e operação

| # | Decisão | Recomendação |
|---|---|---|
| 15 | Collation do PostgreSQL: ICU pt-BR (muda a ordem das listas com acentos, para melhor) | sim |
| 16 | Onde ensaiar a migração com a cópia real do banco | recurso PostgreSQL temporário no servidor de produção, sem porta pública, apagado ao final |
| 17 | Destino e custo da cópia de backup fora do servidor (S3 compatível) | um bucket com criptografia e retenção 7/4/6 |
| 18 | Manter as sessões na migração (ninguém precisa entrar de novo) ou forçar novo login | manter |
| 19 | Contas de teste por perfil para a conferência pós-migração em produção | criar, marcadas como teste, sem dados pessoais |

## Dados e regras da escola

| # | Decisão | Recomendação |
|---|---|---|
| 20 | Fornecer um **modelo em branco** da ficha de cadastro da SEDUC e do TCE para conferir o dicionário de dados | sim; sem dados de pessoas |
| 21 | `Estagio`: número e data do TCE e apólice de seguro são obrigatórios? | número e data opcionais; apólice só se a ficha exigir |
| 22 | Retenção dos dados de quem não é estudante (supervisores, responsáveis, contatos de concedente) e do IP das candidaturas | vínculo encerrado + 5 anos para pessoas; 6 meses para IP |
| 23 | Calendário de 2027: as Etapas 0 a 2 até janeiro não cabem; aceitar a reordenação proposta em [05](05-riscos-e-esforco.md) | aceitar |
| 24 | Quando abre a captação de concedentes de 2027 e se a renovação com as de 2026 precisa acontecer antes (antecipar a Etapa 4) | informar as datas |
