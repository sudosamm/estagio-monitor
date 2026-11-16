// Pequenos comportamentos de interface (sem dependências)
document.addEventListener("click", (ev) => {
  // fecha menus <details class="drop"> ao clicar fora
  document.querySelectorAll("details.drop[open], details.nav-secao[open]").forEach((d) => { if (!d.contains(ev.target)) d.removeAttribute("open"); });
});
document.addEventListener("submit", (ev) => {
  const msg = (ev.submitter && ev.submitter.dataset.confirmar) || ev.target.getAttribute("data-confirmar");
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
// horas por dia: livres (4, 5, 7, 5,5…). Com entrada e saída, calcula pelos horários;
// carga de até 4 horas não tem intervalo, então os campos de intervalo somem.
document.querySelectorAll("input[data-horas-dia]").forEach((campoHoras) => {
  const form = campoHoras.form;
  if (!form) return;
  const pegar = (sufixo) => form.querySelector(`input[name$='${sufixo}']`);
  const ent = pegar("horario_entrada"), si = pegar("saida_intervalo"), vi = pegar("volta_intervalo"), sai = pegar("horario_saida");
  const intervalos = form.querySelectorAll("input[data-intervalo]");
  const min = (i) => { if (!i || !i.value) return null; const [h, m] = i.value.split(":").map(Number); return h * 60 + m; };
  let automatico = !campoHoras.value;
  const ajustarIntervalo = () => {
    const h = parseFloat((campoHoras.value || "").replace(",", "."));
    const semIntervalo = h > 0 && h <= 4 && !(si && si.value) && !(vi && vi.value);
    intervalos.forEach((i) => { const c = i.closest(".campo"); if (c) c.hidden = semIntervalo; });
  };
  const calcular = () => {
    const e = min(ent), s = min(sai);
    if (e == null || s == null || !automatico) return;
    let total = s - e;
    if (min(si) != null && min(vi) != null) total -= min(vi) - min(si);
    if (total > 0) campoHoras.value = String(Math.round(total / 60 * 100) / 100).replace(".", ",");
    ajustarIntervalo();
  };
  campoHoras.addEventListener("input", () => { automatico = !campoHoras.value; ajustarIntervalo(); });
  [ent, si, vi, sai].forEach((i) => i && i.addEventListener("change", calcular));
  ajustarIntervalo();
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
    const mun = caixa("id_municipio"), curso = caixa("id_curso"), conc = caixa("id_concedente");
    if (mun) mun.hidden = v !== "MUNICIPIO";
    if (conc) conc.hidden = v !== "CONCEDENTE";
    if (curso) curso.hidden = v !== "ESCOLA";
  };
  radios.forEach((r) => r.addEventListener("change", atualizar));
  atualizar();
})();
// app instalável (PWA): registra o service worker e oferece o botão "Instalar no celular"
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => { navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {}); });
}
(() => {
  const botoes = document.querySelectorAll("[data-instalar]");
  if (!botoes.length || window.matchMedia("(display-mode: standalone)").matches || navigator.standalone) return;
  let pedido = null;
  window.addEventListener("beforeinstallprompt", (ev) => {
    ev.preventDefault();
    pedido = ev;
    botoes.forEach((b) => { b.hidden = false; });
  });
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  if (ios) botoes.forEach((b) => { b.hidden = false; });
  botoes.forEach((b) => b.addEventListener("click", async () => {
    if (pedido) {
      pedido.prompt();
      await pedido.userChoice;
      pedido = null;
      botoes.forEach((x) => { x.hidden = true; });
    } else if (ios) {
      window.alert("No iPhone: toque em Compartilhar (quadrado com seta) e depois em “Adicionar à Tela de Início”.");
    }
  }));
  window.addEventListener("appinstalled", () => botoes.forEach((x) => { x.hidden = true; }));
})();
// check-in com localização: pede a posição do celular só na hora de marcar entrada/saída
document.addEventListener("submit", (ev) => {
  const form = ev.target;
  if (ev.defaultPrevented || !form.hasAttribute || !form.hasAttribute("data-geo") || form.dataset.geoPronto) return;
  ev.preventDefault();
  const btn = ev.submitter || form.querySelector("button[type=submit]");
  const textoOriginal = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.textContent = "Conferindo localização…"; }
  const campo = (nome, valor) => {
    let i = form.querySelector(`input[name="${nome}"]`);
    if (!i) { i = document.createElement("input"); i.type = "hidden"; i.name = nome; form.appendChild(i); }
    i.value = valor;
  };
  const enviar = () => {
    form.dataset.geoPronto = "1";
    if (btn) { btn.innerHTML = textoOriginal; }
    if (btn && btn.name) campo(btn.name, btn.value);
    form.submit();
  };
  if (!("geolocation" in navigator)) { campo("geo_erro", "sem_suporte"); enviar(); return; }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      campo("geo_lat", pos.coords.latitude); campo("geo_lng", pos.coords.longitude);
      campo("geo_precisao", Math.round(pos.coords.accuracy || 0)); enviar();
    },
    (err) => { campo("geo_erro", { 1: "negada", 2: "indisponivel", 3: "tempo" }[err.code] || "indisponivel"); enviar(); },
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
  );
});
// ficha da concedente: preencher latitude/longitude com a posição atual
document.querySelectorAll("[data-minha-posicao]").forEach((b) => {
  b.hidden = !("geolocation" in navigator);
  b.addEventListener("click", () => {
    const original = b.textContent;
    b.disabled = true; b.textContent = "Obtendo posição…";
    navigator.geolocation.getCurrentPosition((pos) => {
      document.getElementById("id_latitude").value = pos.coords.latitude.toFixed(6);
      document.getElementById("id_longitude").value = pos.coords.longitude.toFixed(6);
      b.disabled = false; b.textContent = `Posição preenchida (precisão de ${Math.round(pos.coords.accuracy)} m)`;
    }, () => { b.disabled = false; b.textContent = original; window.alert("Não foi possível obter a localização. Permita o acesso no navegador."); },
    { enableHighAccuracy: true, timeout: 15000 });
  });
});

// notificações no celular (Web Push): ativar/desativar por aparelho
(() => {
  const cards = document.querySelectorAll("[data-push]");
  if (!cards.length) return;
  const suporta = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const instalado = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const token = document.querySelector("[name=csrfmiddlewaretoken]");
  const post = (url, corpo) => fetch(url, {
    method: "POST", credentials: "same-origin", body: JSON.stringify(corpo || {}),
    headers: { "Content-Type": "application/json", "X-CSRFToken": token ? token.value : "" },
  }).then((r) => r.json());
  const chaveBytes = (s) => {
    const raw = atob((s + "=".repeat((4 - (s.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  let dispensado = false;
  try { dispensado = localStorage.getItem("push-dispensado") === "1"; } catch (e) { /* sem armazenamento */ }
  cards.forEach(async (card) => {
    const q = (s) => card.querySelector(s);
    const lembrete = card.hasAttribute("data-push-lembrete");
    const texto = q("[data-push-texto]");
    const original = texto.textContent;
    if (!suporta) {
      if (ios && !instalado && !lembrete) { card.hidden = false; q("[data-push-ios]").hidden = false; }
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    let insc = await reg.pushManager.getSubscription();
    if (insc) post("/push/inscrever/", insc.toJSON()).catch(() => {});  // mantém o servidor em dia
    if (lembrete && (insc || Notification.permission === "denied" || dispensado)) return;
    const mostrar = () => {
      const ativo = !!insc;
      const negado = Notification.permission === "denied";
      q("[data-push-ativar]").hidden = ativo || negado;
      q("[data-push-desativar]").hidden = !ativo;
      q("[data-push-testar]").hidden = !ativo;
      q("[data-push-bloqueado]").hidden = !negado;
      texto.textContent = ativo ? "Notificações ativadas neste aparelho. Os avisos chegam mesmo com o app fechado." : original;
    };
    card.hidden = false;
    mostrar();
    q("[data-push-ativar]").addEventListener("click", async (ev) => {
      ev.target.disabled = true;
      try {
        const permissao = await Notification.requestPermission();
        if (permissao === "granted") {
          const { ativo, chave } = await fetch("/push/chave/", { credentials: "same-origin" }).then((r) => r.json());
          if (ativo) {
            insc = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chaveBytes(chave) });
            await post("/push/inscrever/", insc.toJSON());
          }
        }
      } catch (e) {
        texto.textContent = "Não foi possível ativar neste navegador.";
      }
      ev.target.disabled = false;
      mostrar();
    });
    q("[data-push-desativar]").addEventListener("click", async () => {
      if (insc) { await post("/push/cancelar/", { endpoint: insc.endpoint }).catch(() => {}); await insc.unsubscribe(); }
      insc = null;
      mostrar();
    });
    q("[data-push-testar]").addEventListener("click", async (ev) => {
      const r = await post("/push/teste/").catch(() => ({ ok: false }));
      ev.target.textContent = r.ok ? "Enviado! Confira as notificações" : "Não chegou: tente desativar e ativar de novo";
    });
    const dispensar = q("[data-push-dispensar]");
    if (dispensar) dispensar.addEventListener("click", () => {
      try { localStorage.setItem("push-dispensado", "1"); } catch (e) { /* ok */ }
      card.hidden = true;
    });
  });
})();
// menu de seções: só uma aberta por vez; Esc fecha
document.querySelectorAll("details.nav-secao").forEach((d) => {
  d.addEventListener("toggle", () => {
    if (d.open) document.querySelectorAll("details.nav-secao[open]").forEach((o) => { if (o !== d) o.open = false; });
  });
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") document.querySelectorAll("details.nav-secao[open], details.drop[open]").forEach((d) => { d.open = false; });
});
// troca de tema sem recarregar a página
document.querySelectorAll("[data-tema-form]").forEach((form) => {
  form.addEventListener("submit", async (ev) => {
    const botao = ev.submitter;
    if (!botao || !window.fetch) return;
    ev.preventDefault();
    const dados = new FormData(form);
    dados.set("tema", botao.value);
    try {
      const r = await fetch(form.action, { method: "POST", body: dados, headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
      const { tema } = await r.json();
      document.documentElement.setAttribute("data-preferencia", tema);
      if (window.aplicarTema) window.aplicarTema();
      form.querySelectorAll("button").forEach((b) => b.classList.toggle("ativo", b === botao));
      setTimeout(() => { botao.disabled = false; }, 0);
    } catch (e) { form.submit(); }
  });
});
// “O que há de novo”: abre sozinho e fecha sem recarregar a página
(() => {
  const dialogo = document.getElementById("novidades-popup");
  if (!dialogo || typeof dialogo.showModal !== "function") return;
  setTimeout(() => dialogo.showModal(), 400);
  const form = dialogo.querySelector("form");
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const dados = new FormData(form);
    dados.set("acao", ev.submitter ? ev.submitter.value : "fechar");
    dialogo.close();
    try {
      await fetch(form.action, { method: "POST", body: dados, credentials: "same-origin", headers: { "X-Requested-With": "fetch" } });
    } catch (e) { /* tenta de novo no próximo acesso */ }
  });
  dialogo.addEventListener("cancel", () => {  // Esc conta como “fechar”
    const dados = new FormData(form);
    dados.set("acao", "fechar");
    fetch(form.action, { method: "POST", body: dados, credentials: "same-origin", headers: { "X-Requested-With": "fetch" } }).catch(() => {});
  });
})();
// contador de caracteres como no SICE (“1000 caracteres restantes”)
document.querySelectorAll("textarea[maxlength]").forEach((t) => {
  const aviso = (t.parentElement && t.parentElement.querySelector("[data-restantes]"))
    || (t.closest(".campo") && t.closest(".campo").parentElement.querySelector("[data-restantes]"));
  if (!aviso) return;
  const atualizar = () => { aviso.textContent = `${t.maxLength - t.value.length} caracteres restantes`; };
  t.addEventListener("input", atualizar);
  atualizar();
});
