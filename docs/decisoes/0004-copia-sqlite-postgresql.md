# 0004 — Cópia dos dados do SQLite para o PostgreSQL

- **Situação:** aceita (Etapa 1, 26/11/2026). Corrige o plano da Etapa 0 ([04](../diagnostico/04-migracao-postgresql.md)).
- **Decide:** o comando exato da cópia e a conferência.

## Contexto

O plano da Etapa 0 recomendava `dumpdata --natural-foreign --natural-primary` em JSON. Ao testar o caminho completo
(`core/test_postgres.py`) apareceram três problemas:

1. **`--natural-primary` troca os ids das contas.** `Usuario` tem chave natural (o `username`), então o `id` some do
   arquivo e o `loaddata` numera de novo. As sessões (`_auth_user_id`), os links e os códigos que guardam o id da conta
   deixariam de valer, e os ids com buraco seriam compactados.
2. **O JSON do Django corta os microssegundos** das datas e horas (`12:30:15.123456` vira `12:30:15.123`). A cópia não
   ficaria idêntica, e a comparação acusaria diferença em todas as tabelas com carimbo de data.
3. **Com o escopo por escola**, o `dumpdata` usa o gerenciador padrão. Sem `--all`, com várias escolas, ele falharia
   (escopo ausente); com uma escola, funciona, mas `--all` deixa claro que nada fica de fora.

## Opções

- XML do Django (preserva a precisão), mas recusa caracteres de controle em textos, que o SQLite aceita.
- `pgloader` (descartado na Etapa 0: converte tipos por conta própria).
- **Formato `jsonlp`**: o `jsonl` do Django com um codificador que preserva os microssegundos
  (`core/serializacao_precisa.py`), registrado em `SERIALIZATION_MODULES`.

## Decisão

```bash
python manage.py dumpdata --all --natural-foreign --exclude contenttypes --exclude auth.permission \
  --format jsonlp -o /data/migracao/dados.jsonlp.gz
python manage.py loaddata /data/migracao/dados.jsonlp.gz        # com DATABASE_URL do banco novo
python manage.py comparar_bancos --origem sqlite:////data/migracao/db-antes-postgres.sqlite3
```

- Sem `--natural-primary`: os ids de todas as tabelas são preservados. `--natural-foreign` continua, porque os tipos de
  conteúdo e as permissões são recriados pelo `migrate` com ids que podem mudar.
- `comparar_bancos` compara linhas, maior id e um resumo SHA-256 dos valores de cada tabela (via ORM, então SQLite e
  PostgreSQL são comparáveis). Tipos de conteúdo e permissões são comparados pela chave natural.

## Consequências

- A ida e volta (migrate, dumpdata, loaddata, comparar) roda nos testes com dois SQLite. No PostgreSQL ela precisa do
  ensaio na homologação (não havia PostgreSQL no ambiente do agente).
- O arquivo `.jsonlp.gz` contém todos os dados pessoais: fica só em `/data/migracao/` durante a janela e é apagado
  depois do ensaio ou da troca. Nunca vai para a pasta do projeto nem para o Git.
