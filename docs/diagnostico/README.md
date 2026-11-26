# Diagnóstico — Etapa 0 (25/11/2026)

Diagnóstico e plano para o piloto de 2027 e a preparação para várias escolas. Nenhum comportamento do sistema foi
alterado: nesta etapa só foram criados arquivos em `docs/` e ajustados o `.gitignore` e o `.dockerignore`.

| # | Documento | Conteúdo |
|---|---|---|
| 00 | [Dados pessoais no Git](00-dados-pessoais-no-git.md) | **achado urgente**: banco, TCEs, CSV e PDF versionados e enviados ao GitHub |
| 01 | [Inventário das telas](01-inventario-telas.md) | 170 rotas por perfil: URL, view, permissão, template; menus atuais |
| 02 | [Modelo de dados atual](02-modelo-de-dados-atual.md) | 41 modelos, relações, campos pessoais, arquivos |
| 03 | [Pontos de escola única](03-pontos-de-escola-unica.md) | configuração, unicidades, tarefas, e-mails, uploads, push, tokens, textos fixos |
| 04 | [Migração para o PostgreSQL](04-migracao-postgresql.md) | ensaio, procedimento, reversão, backup e restauração |
| 05 | [Riscos e esforço](05-riscos-e-esforco.md) | riscos para o piloto, estimativa por etapa, calendário |
| 06 | [Decisões pendentes](06-decisoes-pendentes.md) | o que depende de você |

Outros documentos desta etapa:

- [ADR 0001 — Arquitetura para várias escolas](../decisoes/0001-arquitetura-multiescola.md)
- [Dicionário de dados (rascunho)](../modelo-de-dados.md)

Nenhum dado real foi aberto, copiado ou usado. As pastas e arquivos com dados pessoais (`TCEs/`, `importacao/`,
`Relatorio-estagio/`, `data/`, `sicereport.pdf`, `file.csv`, `.env`) não foram lidos; a verificação do histórico do
Git leu só nomes de arquivos e metadados de commits.

## Etapa 1 (26/11/2026)

- [ADR 0002 — Escopo por escola](../decisoes/0002-escopo-por-escola.md)
- [ADR 0003 — Backup do volume de dados](../decisoes/0003-backup-do-volume-de-dados.md)
- [ADR 0004 — Cópia do SQLite para o PostgreSQL](../decisoes/0004-copia-sqlite-postgresql.md)
- Operação: [backup](../operacao/backup.md) · [troca para o PostgreSQL](../operacao/migracao-postgresql.md) ·
  [deploy multiescola](../operacao/deploy-multiescola.md)
