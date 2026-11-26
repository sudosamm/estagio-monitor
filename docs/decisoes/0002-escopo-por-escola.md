# 0002 — Como o escopo por escola é aplicado

- **Situação:** aceita (Etapa 1, 26/11/2026).
- **Decide:** o mecanismo único que impede uma escola de ver dados de outra, dentro da opção (b) do
  [ADR 0001](0001-arquitetura-multiescola.md).

## Contexto

- São cerca de 170 rotas, mais buscas, exportações, formulários, tarefas e links públicos. Aplicar um filtro
  `escola=` à mão em cada consulta deixaria esquecimentos, e um esquecimento vaza dados.
- Em 2027 haverá uma escola só. A mudança não pode alterar nada para ela, nem exigir que todo o código conheça a escola
  de imediato.
- As contas são globais (um login por pessoa), então `Usuario` não pode ser filtrado como as outras tabelas.

## Opções

1. **Filtro explícito em cada view** (`.filter(escola=request.escola)`): simples de ler, mas depende de lembrar em
   cada um dos ~250 pontos de consulta; o padrão do erro é "mostra tudo".
2. **Gerenciador padrão com escopo** (`objects` filtra pela escola atual, lida de um contextvar), com saída explícita
   para ver todas: cobre de uma vez as views, os formulários (listas de escolha), `get_object_or_404`, os
   gerenciadores reversos (`curso.estagios`) e o admin. O padrão do erro passa a ser "não mostra nada".
3. **Row-Level Security do PostgreSQL**: isolamento no banco, mas só no PostgreSQL (a transição ainda passa pelo
  SQLite), com a escola da conexão definida a cada requisição e testes mais difíceis. Fica como segunda camada para
  depois do piloto, se um contrato exigir.

## Decisão

Opção 2, em `escolas/escopo.py`:

- `ESCOLA_ATUAL` (contextvar) guarda a escola em uso. O `EscolaAtualMiddleware` a define pela conta (vínculos e
  seletor) ou pelo caminho público (`/seja-concedente/<slug>/`). Comandos e tarefas usam `escola_ativa(escola)`.
- Os modelos com escola declaram `_caminho_escola` (`"escola"`, `"estagio__escola"`, `"curso__escola"`…) e usam
  `EscopoEscolaManager`. O filtro usa uma expressão (`EscolaDaConsulta`) resolvida **na execução** da consulta: um
  queryset criado no carregamento de um módulo usa a escola do momento em que é avaliado.
- **Falha fechada:** sem escola definida e com duas ou mais escolas no banco, a consulta levanta `EscopoAusente`
  (que vira 403 numa requisição). Com uma escola só, ela é usada automaticamente: a instalação de hoje funciona sem
  nenhuma mudança, e o código não depende de existir mais de uma escola (a opção "uma instalação por escola" continua
  possível).
- Ver todas as escolas é sempre explícito: `Modelo.objects.todas_as_escolas()` ou `with todas_as_escolas():`
  (administrador da plataforma no `/admin/`, tarefas que percorrem as escolas, agenda iCal da pessoa, links públicos
  procurados pelo código).
- `_base_manager` (usado pelo Django para seguir relações, salvar e apagar) não tem filtro.
- **Pessoas:** `escolas.pessoas.na_escola(qs)` restringe às contas com vínculo ativo na escola (listas de contas,
  busca, escolhas de orientador e supervisor, telas por id de conta). `administradores()` dá os administradores da
  escola.
- **Defesa em profundidade:** `Estagio.pode_ver` recusa estágio de outra escola mesmo que o objeto chegue por outro
  caminho; os campos `escola` têm `default` pela escola em uso e não aparecem nos formulários.
- **Papel por escola:** o middleware ajusta, só na requisição, `user.papel` e `user.is_superuser` para a escola atual.
  Com uma escola só, valem o papel e o administrador gravados (mais o vínculo `ADMIN`), exatamente como antes.
  `Usuario.save` grava sempre os valores originais.
- **Threads:** `core.threads.iniciar_thread` copia o contexto (a escola) para a thread de e-mail e push.

## Consequências

- Uma tela nova que usa `Modelo.objects` já nasce com escopo. O que precisa de cuidado manual são consultas a `Usuario`
  (use `na_escola`), SQL cru e `todas_as_escolas()`.
- Uma consulta a mais por requisição com login (os vínculos da conta). As demais leituras são as mesmas; o filtro entra
  como condição na mesma consulta.
- `dumpdata` usa o gerenciador padrão: na cópia de banco, use `--all` (ver
  [0004](0004-copia-sqlite-postgresql.md)).
- Os testes de isolamento (`core/test_multiescola.py`) criam as escolas A e B. Com o filtro desligado de propósito,
  13 verificações falham, o que confirma que os testes detectam vazamento.
- Pendente para a expansão: um teste que percorra o `urls.py` e exija cobertura A/B de cada rota nova (hoje a
  cobertura é por amostra das telas principais).
