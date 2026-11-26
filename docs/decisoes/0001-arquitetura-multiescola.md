# 0001 — Arquitetura para várias escolas

- **Situação:** aceita (aprovada na Etapa 0; implementada na Etapa 1, 26/11/2026). Como o escopo é aplicado:
  [ADR 0002](0002-escopo-por-escola.md).
- **Decide:** como várias escolas usam o mesmo sistema com dados isolados, configuração e identidade próprias, sem
  cópia de código por escola.

## Contexto

- Hoje o sistema atende uma escola. A escola é implícita: `Configuracao` é um registro único (`pk = 1`), `Curso.nome`
  e `ModeloEmail.tipo` são únicos no sistema, o administrador da escola é o `is_superuser` e cada conta tem um papel
  só (`Usuario.papel`). O levantamento completo está em
  [03-pontos-de-escola-unica.md](../diagnostico/03-pontos-de-escola-unica.md).
- O escopo de dados já é centralizado em boa parte: `estagios_visiveis(user)` em `core/services.py` e as checagens
  por objeto (`Estagio.pode_ver`, `pegar_estagio`). Mas o superusuário vê "tudo", e "tudo" hoje é a escola inteira.
- Banco: SQLite em `/data`, um container no Coolify. Volume pequeno: uma escola tem por volta de uma centena de
  estagiários por ano; dez escolas continuam sendo um banco pequeno para o PostgreSQL.
- Em 2027 o piloto roda numa escola. A expansão só acontece depois, se o piloto for bem. A arquitetura precisa estar
  pronta, mas a escola atual não pode sentir diferença.
- Exigências do plano: uma pessoa pode ter vários papéis e atuar em mais de uma escola **com um login só**; o
  administrador da plataforma é separado do administrador da escola; nenhuma listagem, busca, exportação, download,
  link assinado ou importação funciona sem escopo.
- Equipe: uma pessoa desenvolve e opera. Custo de operação pesa tanto quanto o de desenvolvimento.

## Opções

### (a) Uma instalação por escola

Um deploy (container + banco + volume) por escola, com o mesmo código.

- **A favor:** isolamento máximo e simples de explicar a uma secretaria ("o banco da sua escola é só seu"); quase
  nenhuma mudança no código (só tirar os textos fixos); um problema numa escola não afeta as outras; exclusão e
  portabilidade dos dados de uma escola são triviais.
- **Contra:** custo e trabalho crescem com cada escola: N deploys, N bancos, N backups, N migrations a cada versão, N
  configurações de e-mail, push e domínio. Uma pessoa em duas escolas tem **duas contas e dois logins**, o que fere a
  exigência de conta única. Sem visão da rede (indicadores entre escolas, administração da plataforma). Versões
  podem divergir entre escolas.

### (b) Banco compartilhado com coluna `escola` (row-level)

Um deploy e um banco. As entidades-raiz ganham `escola`; as demais herdam pela relação. Um middleware define a escola
atual; managers/querysets aplicam o filtro.

- **A favor:** um deploy, um backup, uma migration por versão; conta global por pessoa com `VinculoEscola`, como o
  plano pede; o administrador da plataforma enxerga a rede; o Django e o código atual já estão organizados assim
  (escopo central em `estagios_visiveis`, contextvar por requisição). Funciona igual em SQLite e PostgreSQL, o que
  deixa a migração de banco e a de arquitetura independentes.
- **Contra:** o isolamento depende do código. Um filtro esquecido vaza dados de outra escola. Exige disciplina e
  testes de isolamento A/B em todas as telas. Unicidades passam a ser compostas. Uma escola muito grande ou com
  exigência contratual de banco próprio não cabe sem uma instalação separada.

### (c) Schema por escola no PostgreSQL

Um banco com um *schema* por escola (por exemplo, com `django-tenants`); o `search_path` muda conforme a escola.

- **A favor:** isolamento forte no banco sem multiplicar deploys; as tabelas de cada escola nem se enxergam.
- **Contra:** prende o sistema ao PostgreSQL e a uma biblioteca externa que mexe no roteamento de banco; migrations
  rodam uma vez por schema (o `migrate` do `entrypoint.sh` fica mais lento e mais arriscado a cada escola); a conta
  global por pessoa e o `VinculoEscola` ficam no schema público, com chaves estrangeiras atravessando schemas, que é
  justamente o caso mais difícil dessas bibliotecas; testes ficam mais lentos e complexos; a visão da rede exige
  consultar todos os schemas. Não roda em SQLite, então a migração de arquitetura e a de banco viram uma só, sem
  caminho de volta simples.

## Comparação

| Critério | (a) instalação por escola | (b) coluna `escola` | (c) schema por escola |
|---|---|---|---|
| Isolamento | físico | por código (+ testes) | no banco |
| Conta única por pessoa | **não** | sim | difícil |
| Operação (deploy, backup, migration) | N vezes | 1 vez | 1 deploy, N migrations |
| Mudança no código | pequena | grande, mas incremental | grande + biblioteca nova |
| Compatível com SQLite durante a transição | sim | sim | não |
| Visão da rede / administrador da plataforma | não | sim | trabalhosa |
| Exclusão dos dados de uma escola | apagar o deploy | comando de exportação/exclusão (Etapa 7) | apagar o schema |
| Risco para o piloto de 2027 | baixo | médio (mitigável) | alto |

## Decisão (recomendada)

**Opção (b): banco compartilhado com isolamento por escola, conta global por pessoa e vínculos por escola**, como o
plano já indicava. Com estas salvaguardas:

1. **Escopo que falha fechado.** Um manager/queryset único (`da_escola(escola)`) e um middleware que coloca a escola
   atual no contextvar que já existe (`CACHE_REQUISICAO`). Nos modelos com escola, uma consulta sem escola definida e
   sem opt-out explícito (`todas_as_escolas()`, só para a plataforma e para as tarefas que percorrem as escolas)
   **levanta erro**, em vez de devolver tudo.
2. **`escola` gravada nas entidades-raiz** (cursos, concedentes, candidaturas, estágios, feriados e eventos, avisos,
   tipos de documento, perguntas, modelos de e-mail, agendamentos, folhas enviadas, documentos gerais, links de
   confirmação). As tabelas filhas do estágio herdam pela relação; `Estagio.escola` fica redundante com o curso de
   propósito, para índices e para filtros simples.
3. **Testes de isolamento A/B** para todas as rotas do inventário, inclusive por URL direta, token e link assinado.
   Um teste percorre o `urls.py` e falha se uma rota nova não estiver coberta.
4. **Downloads** sempre conferem a escola do objeto, e os arquivos novos vão para `escolas/<id>/…`.
5. **Administrador da plataforma** (`is_superuser`, técnico) separado do **administrador da escola** (papel no
   `VinculoEscola`). O `/admin/` do Django fica só para a plataforma.
6. **Segunda camada depois do piloto (opcional):** *Row-Level Security* do PostgreSQL com a escola da conexão, se a
   rede ou um contrato pedir isolamento no banco. Não é necessária para o piloto.

A opção (a) continua disponível como saída para um caso específico (uma rede que exija banco próprio): o mesmo código,
com uma escola só, roda como hoje. Por isso o código não deve depender de existir mais de uma escola.

## Consequências

- Etapa 1 grande, mas incremental: primeiro `Escola` e a migration que associa tudo à escola atual (reversível, com
  contagens); depois o escopo obrigatório, tela por tela, com os testes A/B; por último as unicidades compostas.
- Toda view, exportação, busca, mapa, indicador, notificação, push, download, link assinado e importação passa pelo
  escopo. O inventário de telas ([01-inventario-telas.md](../diagnostico/01-inventario-telas.md)) é a lista de
  conferência.
- `Configuracao.atual()` continua existindo (compatibilidade), resolvendo a escola da requisição; fora de requisição
  (tarefas, comandos), a escola é passada explicitamente.
- As tarefas periódicas percorrem as escolas e usam a configuração e o fuso de cada uma.
- `Usuario.papel` continua como papel principal em 2027, preenchido a partir do vínculo; as checagens de permissão
  passam a usar o papel na escola atual.
- A migração para o PostgreSQL ([04-migracao-postgresql.md](../diagnostico/04-migracao-postgresql.md)) pode ser feita
  antes, junto ou depois da mudança de arquitetura. Recomendação: **PostgreSQL primeiro**, num deploy só de troca de
  banco, sem mudança de modelo; a migration multiescola vem num deploy seguinte. Cada passo tem sua própria reversão.
- Custo contínuo: cada tela nova precisa de escopo e de teste A/B. O teste que percorre o `urls.py` impede esquecer.
