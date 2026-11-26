# 05 — Riscos para o piloto e estimativa de esforço

## Riscos para o piloto de 2027

Probabilidade (P) e impacto (I): A alto · M médio · B baixo.

| # | Risco | P | I | Mitigação |
|---|---|---|---|---|
| 1 | **Dados pessoais já versionados no Git e enviados ao GitHub**, e TCEs/CSV/PDF dentro da imagem Docker ([00](00-dados-pessoais-no-git.md)) | já ocorreu | A | desversionar, reescrever o histórico, rotacionar segredos se o banco versionado for da produção, avaliar comunicação LGPD; `.dockerignore` corrigido |
| 2 | Regressão na escola atual por causa da refatoração multiescola no 1º semestre | M | A | deploys pequenos; homologação antes; migration reversível com contagens; testes atuais (298) sempre verdes; nada de migration arriscada no 2º semestre |
| 3 | Vazamento entre escolas por filtro esquecido | B em 2027 (uma escola no piloto); A na expansão | A | escopo que falha fechado; teste que percorre o `urls.py`; testes A/B |
| 4 | Falha na migração para o PostgreSQL (dados que o SQLite aceitou e o PostgreSQL recusa) | M | M | `verificar_para_postgres`, dois ensaios, reversão R1/R2 ([04](04-migracao-postgresql.md)) |
| 5 | Backup nunca testado; hoje é "copiar o volume" | A | A | backup agendado + cópia fora do servidor + teste mensal de restauração antes do piloto |
| 6 | Tarefas com hora marcada dependem do tráfego (não há cron): o resumo de segunda e os lembretes só saem quando alguém acessa | M | M | usar as *Scheduled Tasks* do Coolify chamando comandos (decisão pendente); manter o disparo pelo tráfego como reserva |
| 7 | Carga do piloto (famílias e supervisores entrando ao mesmo tempo) no SQLite | M | M | PostgreSQL antes do piloto |
| 8 | Importação de maio/junho com regras atuais: supervisores identificados só pelo nome, cursos criados por erro de digitação, prévia com dados pessoais na sessão | A | M | central de importação da Etapa 2 antes de maio |
| 9 | Ambiente de testes alcançar pessoas reais (e-mail, push) | B | A | homologação sem `EMAIL_HOST` real (ou com `EMAIL_CONSOLE=1`), `PUSH_ATIVO=0`, só `popular_demo`; conferir as variáveis no Coolify |
| 10 | Segredo da verificação em duas etapas guardado em texto claro (`totp_segredo`) | B | A | cifrar em repouso com uma chave fora do banco (sugestão para a Etapa 1; decisão pendente) |
| 11 | `is_superuser` = administrador da escola = acesso total ao `/admin/` do Django | M | M | separar administrador da plataforma e da escola (Etapa 1) |
| 12 | Calendário apertado: as Etapas 0 a 2 até janeiro não cabem no esforço estimado abaixo | A | M | reordenar (ver "Calendário") |
| 13 | Operação por uma pessoa só (desenvolvimento, deploy, suporte) | A | M | procedimentos escritos (este diagnóstico, o plano de migração), canal de suporte e registro de incidentes (Etapa 6) |
| 14 | Textos e regras presos ao SICE e ao Ceará dificultam a expansão para outras redes | — | B no piloto | `RedeEnsino` na Etapa 1, mantendo a aparência atual |
| 15 | Termos e Aviso de Privacidade sem revisão para o piloto com famílias | M | M | nova versão e novo aceite (Etapa 6); revisão jurídica |
| 16 | Arquivos da pasta do estágio gravados com o nome original (pode trazer o nome do estudante no disco e nos backups) | A | B | nome aleatório para arquivos novos (Etapa 1) |

## Estimativa de esforço por etapa

Dias de trabalho de uma pessoa com o agente, incluindo testes, revisão e deploy em homologação. São faixas: o
diagnóstico reduz a incerteza da Etapa 1, mas as Etapas 4 a 6 dependem de decisões ainda abertas.

| Etapa | Conteúdo principal | Esforço |
|---|---|---|
| 0 | diagnóstico e plano (esta entrega) | 1 dia |
| 1 | PostgreSQL (2–3), `Escola`/`RedeEnsino`/configuração (2), escopo obrigatório em 170 rotas, tarefas, arquivos e links (6–9), vínculos e separação dos administradores (3–4), unicidades e migration de dados (2), textos e marca (2), testes A/B (4–5) | **21–27 dias** |
| 2 | dicionário final (2), `ContatoConcedente` (1), central de importação com 10 entidades, 3 modos, prévia no servidor, lotes, relatórios e pacote .xlsx compatível (12–18), documentação e ajuda (2) | **17–23 dias** |
| 3 | navegação desktop e mobile, fonte única de menus, redirecionamentos | 5–8 dias |
| 4 | lista e ficha da concedente, contatos, WhatsApp unificado, renovação anual | 8–12 dias |
| 5 | formulários densos, candidatura em etapas com revisão, padrões de interface, acessibilidade | 10–15 dias |
| 6 | configuração e painel do piloto, pesquisas, guias por perfil, operação, termos | 8–12 dias |
| 7 | implantação em novas escolas (depois do piloto) | 15–25 dias |

## Calendário

A sequência sugerida (Etapas 0 a 2 até janeiro) soma cerca de 40–50 dias de trabalho; de 25/11 ao fim de janeiro há
umas 8 semanas, com festas no meio. Propostas, para você decidir:

1. **Até janeiro:** Etapa 1 (PostgreSQL primeiro; depois a fundação multiescola com a escola atual só).
2. **Fevereiro e março:** Etapa 2 (a central de importação só precisa estar pronta para maio/junho) e, em paralelo ou
   logo depois, a Etapa 4 se a captação ou a renovação das concedentes abrir cedo.
3. **Março e abril:** Etapas 3 e 5.
4. **Maio e junho:** Etapa 6, importações e treinamento, como planejado.

O que puder ficar para depois do piloto sem prejuízo (marcado como decisão pendente): `AnoLetivo`, `Estudante`
(matrícula), a exportação no formato do modelo (Etapa 2, item 5) e o *Row-Level Security*.
