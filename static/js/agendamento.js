// Tela de agendamento do orientador: busca de estagiários, ficha de cada um, preenchimento e avisos.
(() => {
  const form = document.querySelector("[data-agendar]");
  if (!form) return;
  const painel = document.querySelector("[data-fichas]");
  const vazio = document.querySelector("[data-fichas-vazio]");
  const caixas = [...form.querySelectorAll('input[name="estagios"]')];
  const campoData = form.querySelector('[name="data_hora"]');
  const campoLocal = form.querySelector('[name="local"]');
  const campoAssunto = form.querySelector('[name="assunto"]');
  const campoTipo = form.querySelector('[name="tipo"]');
  const campoModalidade = form.querySelector('[name="modalidade"]');
  const avisos = form.querySelector("[data-avisos]");
  const sugestoes = form.querySelector("[data-sugestoes]");
  const ocupada = JSON.parse(document.getElementById("agenda-ocupada").textContent);
  const urlFicha = (id) => form.dataset.fichaUrl.replace(/0\/$/, `${id}/`);
  const fichas = new Map(); // id -> dados do servidor
  let assuntoAutomatico = campoAssunto && !campoAssunto.value ? "" : null;

  const semAcento = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const dataBR = (iso) => iso.slice(8, 10) + "/" + iso.slice(5, 7);
  const DIAS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
  const marcados = () => caixas.filter((c) => c.checked).map((c) => c.value);

  // busca e “só os marcados”
  const busca = form.querySelector("[data-buscar]");
  const soMarcados = form.querySelector("[data-so-marcados]");
  const semResultado = form.querySelector("[data-sem-resultado]");
  const contagem = form.querySelector("[data-contagem]");
  function filtrar() {
    const termo = semAcento(busca.value.trim());
    let visiveis = 0;
    caixas.forEach((c) => {
      const label = c.closest("label");
      const ok = (!termo || semAcento(label.dataset.texto || label.textContent).includes(termo)) && (!soMarcados.checked || c.checked);
      label.hidden = !ok;
      visiveis += ok;
    });
    semResultado.hidden = visiveis > 0;
    const n = marcados().length;
    contagem.textContent = n ? `· ${n} escolhido${n > 1 ? "s" : ""}` : "";
  }
  busca.addEventListener("input", filtrar);
  soMarcados.addEventListener("change", filtrar);

  // fichas
  async function carregar(id) {
    if (!fichas.has(id)) {
      const r = await fetch(urlFicha(id), { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (!r.ok) return;
      fichas.set(id, await r.json());
    }
  }
  async function atualizar() {
    const ids = marcados();
    await Promise.all(ids.map(carregar));
    painel.querySelectorAll("[data-ficha-card]").forEach((el) => { if (!ids.includes(el.dataset.fichaCard)) el.remove(); });
    ids.forEach((id) => {
      const f = fichas.get(id);
      if (!f || painel.querySelector(`[data-ficha-card="${id}"]`)) return;
      const card = document.createElement("div");
      card.className = "card ficha-card";
      card.dataset.fichaCard = id;
      card.innerHTML = f.html; // HTML montado e escapado pelo servidor (template do Django)
      painel.append(card);
    });
    vazio.hidden = ids.length > 0;
    preencher(ids.map((id) => fichas.get(id)).filter(Boolean));
    filtrar();
    verificar();
  }
  painel.addEventListener("click", (ev) => {
    const botao = ev.target.closest("[data-incluir]");
    if (!botao) return;
    const caixa = caixas.find((c) => c.value === botao.dataset.incluir);
    if (caixa && !caixa.checked) { caixa.checked = true; atualizar(); }
    botao.disabled = true;
  });
  caixas.forEach((c) => c.addEventListener("change", atualizar));

  // preenchimento automático (sem apagar o que a pessoa digitou)
  function preencher(lista) {
    if (!lista.length) { sugestoes.hidden = true; return; }
    if (campoLocal && !campoLocal.value && lista[0].local_id) campoLocal.value = String(lista[0].local_id);
    const nomes = lista.map((f) => f.primeiro_nome);
    const tipo = campoTipo && campoTipo.value === "VISITA" ? "Visita de acompanhamento" : "Conversa sobre o estágio";
    const sugerido = `${tipo} — ${nomes.length > 3 ? `${nomes.length} estagiários` : nomes.join(nomes.length === 2 ? " e " : ", ")}`;
    if (campoAssunto && (assuntoAutomatico !== null && campoAssunto.value === assuntoAutomatico || !campoAssunto.value)) {
      campoAssunto.value = sugerido;
      assuntoAutomatico = sugerido;
    }
    // dias de estágio em comum (para a visita encontrar todos no local)
    let comuns = lista[0].dias;
    lista.slice(1).forEach((f) => { comuns = comuns.filter((d) => f.dias.includes(d)); });
    const hora = lista.find((f) => f.entrada)?.entrada || "08:00";
    const chips = sugestoes.querySelector("[data-chips]");
    chips.replaceChildren();
    comuns.slice(0, 8).forEach((d) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "etiqueta botao";
      b.textContent = `${DIAS[new Date(d + "T12:00").getDay()]} ${dataBR(d)} ${hora}`;
      b.addEventListener("click", () => { campoData.value = `${d}T${hora}`; verificar(); });
      chips.append(b);
    });
    if (!comuns.length) chips.append("nenhum dia em comum nos próximos 90 dias");
    sugestoes.hidden = false;
  }

  // avisos: estagiário sem estágio no dia e conflito com outro compromisso
  function verificar() {
    const valor = campoData && campoData.value;
    const msgs = [];
    if (valor) {
      const dia = valor.slice(0, 10);
      const presencial = !campoModalidade || campoModalidade.value === "PRESENCIAL";
      if (campoTipo && campoTipo.value === "VISITA" && presencial) {
        marcados().map((id) => fichas.get(id)).filter(Boolean).forEach((f) => {
          if (!f.dias.includes(dia)) msgs.push(`${f.primeiro_nome} não tem estágio em ${dataBR(dia)} (fora da escala, feriado ou fim do estágio).`);
        });
      }
      const alvo = new Date(valor).getTime();
      ocupada.forEach((a) => {
        const ini = new Date(a.inicio).getTime();
        if (Math.abs(ini - alvo) < Math.max(a.duracao, 60) * 60000) {
          msgs.push(`Você já tem “${a.assunto}” em ${dataBR(a.inicio.slice(0, 10))} às ${a.inicio.slice(11, 16)}.`);
        }
      });
    }
    avisos.replaceChildren(...msgs.map((m) => { const p = document.createElement("div"); p.textContent = m; return p; }));
    avisos.hidden = !msgs.length;
  }
  [campoData, campoTipo, campoModalidade].forEach((c) => c && c.addEventListener("change", verificar));
  if (campoTipo) campoTipo.addEventListener("change", () => preencher(marcados().map((id) => fichas.get(id)).filter(Boolean)));

  filtrar();
  if (marcados().length) atualizar();
})();
