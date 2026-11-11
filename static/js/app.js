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
