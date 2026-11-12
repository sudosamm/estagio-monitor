// Pequenos comportamentos de interface (sem dependências)
document.addEventListener("click", (ev) => {
  // fecha menus <details class="drop"> ao clicar fora
  document.querySelectorAll("details.drop[open]").forEach((d) => { if (!d.contains(ev.target)) d.removeAttribute("open"); });
});
document.addEventListener("submit", (ev) => {
  const msg = ev.target.getAttribute("data-confirmar");
  if (msg && !window.confirm(msg)) { ev.preventDefault(); return; }
  const btn = ev.submitter;
  if (btn && !btn.dataset.semTrava) { setTimeout(() => { btn.disabled = true; }, 0); }
});
// rola o chat para a última mensagem
const chat = document.querySelector(".chat");
if (chat) chat.scrollTop = chat.scrollHeight;
// marcar/desmarcar todos
document.querySelectorAll("[data-marcar-todos]").forEach((el) => {
  el.addEventListener("change", () => {
    document.querySelectorAll(el.dataset.marcarTodos).forEach((c) => { if (!c.closest("label")?.hidden) c.checked = el.checked; });
  });
});
// filtro de texto em listas de checkbox
document.querySelectorAll("[data-filtrar]").forEach((input) => {
  input.addEventListener("input", () => {
    const termo = input.value.toLowerCase();
    document.querySelectorAll(input.dataset.filtrar + " label").forEach((l) => { l.hidden = !l.textContent.toLowerCase().includes(termo); });
  });
});
// carga de 4 horas não tem intervalo: esconde os campos de intervalo
document.querySelectorAll("select[name$='horas_por_dia']").forEach((sel) => {
  const campos = sel.form ? sel.form.querySelectorAll("input[data-intervalo]") : [];
  const ajustar = () => {
    const semIntervalo = sel.value === "4";
    campos.forEach((i) => {
      const c = i.closest(".campo");
      if (c) c.hidden = semIntervalo;
      if (semIntervalo) i.value = "";
    });
  };
  sel.addEventListener("change", ajustar);
  ajustar();
});
// copiar o valor de um campo
document.querySelectorAll("[data-copiar]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const alvo = document.querySelector(btn.dataset.copiar);
    navigator.clipboard?.writeText(alvo.value).then(() => { btn.textContent = "Copiado!"; });
  });
});
// avisos para fora do sistema: os links de WhatsApp/e-mail usam o texto revisado
document.querySelectorAll("form.aviso-externo").forEach((form) => {
  const texto = form.querySelector("textarea");
  const atualizar = () => {
    const msg = encodeURIComponent(texto.value);
    const wa = form.querySelector("[data-canal=whatsapp]");
    if (wa) wa.href = wa.href.split("?")[0] + "?text=" + msg;
    const em = form.querySelector("[data-canal=email]");
    if (em) em.href = "mailto:" + form.dataset.email + "?subject=" + encodeURIComponent(form.dataset.assunto) + "&body=" + msg;
  };
  texto.addEventListener("input", atualizar);
  form.querySelector("[data-copiar-texto]")?.addEventListener("click", (ev) => {
    navigator.clipboard?.writeText(texto.value).then(() => { ev.target.textContent = "Copiado!"; });
  });
});
// supervisor: só mostra quem é da concedente escolhida
document.querySelectorAll("form").forEach((form) => {
  const local = form.querySelector("select[name$='local']");
  const sup = form.querySelector("select[name$='supervisor']");
  if (!local || !sup || !sup.querySelector("option[data-concedentes]")) return;
  const filtrar = () => {
    sup.querySelectorAll("option[data-concedentes]").forEach((op) => {
      const ok = local.value && op.dataset.concedentes.split(",").includes(local.value);
      op.hidden = !ok; op.disabled = !ok;
      if (!ok && op.selected) sup.value = "";
    });
  };
  local.addEventListener("change", filtrar);
  filtrar();
});

// selects que enviam o formulário ao mudar (ex.: escolha do ano de referência)
document.querySelectorAll("select[data-autoenvio]").forEach((sel) => {
  sel.addEventListener("change", () => sel.form && sel.form.submit());
});

// feriados: município só para feriado municipal; curso só para evento da escola
(() => {
  const radios = document.querySelectorAll("input[name=abrangencia]");
  if (!radios.length) return;
  const caixa = (id) => document.getElementById(id)?.closest(".campo");
  const atualizar = () => {
    const v = [...radios].find((r) => r.checked)?.value;
    const mun = caixa("id_municipio"), curso = caixa("id_curso");
    if (mun) mun.hidden = v !== "MUNICIPIO";
    if (curso) curso.hidden = v !== "ESCOLA";
  };
  radios.forEach((r) => r.addEventListener("change", atualizar));
  atualizar();
})();
