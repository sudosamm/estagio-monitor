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
      document.getElementById("id_latitude").dispatchEvent(new Event("change")); // move o alfinete do mapa
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
// “Sua opinião” (período de testes): abre o diálogo e envia sem sair da página
(() => {
  const dlg = document.querySelector("[data-opiniao]");
  if (!dlg) return;
  const form = dlg.querySelector("[data-form-opiniao]");
  const ok = dlg.querySelector("[data-ok-opiniao]");
  const erro = dlg.querySelector("[data-erro-opiniao]");
  document.querySelector("[data-abrir-opiniao]").addEventListener("click", () => {
    form.hidden = false; ok.hidden = true; erro.hidden = true; dlg.showModal();
  });
  dlg.querySelectorAll("[data-fechar-opiniao]").forEach((b) => b.addEventListener("click", () => dlg.close()));
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const botao = form.querySelector('button[type="submit"]');
    botao.disabled = true;
    try {
      const r = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { Accept: "application/json" }, credentials: "same-origin" });
      const dados = await r.json().catch(() => ({}));
      if (r.ok && dados.ok) { form.reset(); form.hidden = true; ok.hidden = false; }
      else { erro.textContent = dados.erro || "Não foi possível enviar agora. Tente de novo."; erro.hidden = false; }
    } catch (e) {
      erro.textContent = "Sem conexão. Tente de novo em instantes."; erro.hidden = false;
    } finally { botao.disabled = false; }
  });
})();
// barra de carregamento no topo enquanto a próxima página chega (dá retorno imediato no celular)
(() => {
  const html = document.documentElement;
  const comecar = () => html.classList.add("navegando");
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[href]");
    if (!a || ev.defaultPrevented || ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    if (a.target === "_blank" || a.hasAttribute("download") || a.origin !== location.origin) return;
    if (a.pathname === location.pathname && a.search === location.search && a.hash) return;
    comecar();
  });
  document.addEventListener("submit", (ev) => {
    const alvo = (ev.submitter && ev.submitter.getAttribute("formtarget")) || ev.target.getAttribute("target");
    if (alvo === "_blank") return;  // abre em outra aba (ex.: WhatsApp): esta página não muda
    setTimeout(() => { if (!ev.defaultPrevented && !ev.target.closest("dialog")) comecar(); }, 0);
  });
  window.addEventListener("pageshow", () => html.classList.remove("navegando"));
})();
// mensagens de sucesso e informação somem sozinhas (os erros ficam)
document.querySelectorAll(".avisos .aviso.success, .avisos .aviso.info").forEach((m) => {
  setTimeout(() => { m.classList.add("saindo"); setTimeout(() => m.remove(), 400); }, 7000);
});

// busca rápida da gestão: botão “Buscar”, tecla “/” ou Ctrl+K
(() => {
  const dlg = document.getElementById("busca-dialogo");
  if (!dlg) return;
  const campo = dlg.querySelector("[data-busca-campo]");
  const caixa = dlg.querySelector("[data-busca-resultados]");
  const dica = caixa.innerHTML;
  let itens = [], atual = -1, timer = null, ultimo = "";
  const abrir = () => { if (!dlg.open) { dlg.showModal(); campo.select(); } };
  document.querySelectorAll("[data-busca-abrir]").forEach((b) => b.addEventListener("click", abrir));
  document.addEventListener("keydown", (ev) => {
    const digitando = ev.target.closest && ev.target.closest("input, textarea, select, [contenteditable]");
    if (document.querySelector("dialog[open]:not(#busca-dialogo)")) return;  // outra janela aberta na frente
    if ((ev.key === "/" && !digitando) || (ev.key.toLowerCase() === "k" && (ev.ctrlKey || ev.metaKey))) {
      ev.preventDefault(); abrir();
    }
  });
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
  function marcar(i) {
    itens.forEach((a, n) => a.classList.toggle("ativo", n === i));
    atual = i;
    if (itens[i]) itens[i].scrollIntoView({ block: "nearest" });
  }
  function mostrar(grupos) {
    caixa.replaceChildren();
    itens = [];
    if (!grupos.length) { const p = document.createElement("p"); p.className = "busca-dica"; p.textContent = "Nada encontrado."; caixa.append(p); return; }
    grupos.forEach((g) => {
      const h = document.createElement("div"); h.className = "busca-grupo"; h.textContent = g.nome; caixa.append(h);
      g.itens.forEach((it) => {
        const a = document.createElement("a"); a.href = it.url; a.className = "busca-item"; a.setAttribute("role", "option");
        const t = document.createElement("strong"); t.textContent = it.titulo; a.append(t);
        if (it.detalhe) { const d = document.createElement("small"); d.textContent = it.detalhe; a.append(d); }
        a.addEventListener("mousemove", () => marcar(itens.indexOf(a)));
        caixa.append(a); itens.push(a);
      });
    });
    marcar(0);
  }
  async function buscar() {
    const q = campo.value.trim();
    if (q === ultimo) return;
    ultimo = q;
    if (q.length < 2) { caixa.innerHTML = dica; itens = []; return; }
    try {
      const r = await fetch(`${dlg.dataset.url}?q=${encodeURIComponent(q)}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (r.ok && campo.value.trim() === q) mostrar((await r.json()).grupos);
    } catch (e) { /* sem conexão: tenta de novo na próxima tecla */ }
  }
  campo.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(buscar, 150); });
  campo.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); marcar(Math.min(atual + 1, itens.length - 1)); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); marcar(Math.max(atual - 1, 0)); }
    else if (ev.key === "Enter" && itens[atual]) { ev.preventDefault(); itens[atual].click(); }
  });
})();
// roteiro de visitas: monta o link do Google Maps com as concedentes marcadas, na ordem da lista
(() => {
  const lista = document.querySelector("[data-roteiro]");
  if (!lista) return;
  const botao = document.querySelector("[data-roteiro-abrir]");
  const contagem = document.querySelector("[data-roteiro-contagem]");
  const MAX = 10;
  function atualizar() {
    const marcadas = [...lista.querySelectorAll("[data-parada]:checked")].map((c) => c.dataset.destino);
    lista.querySelectorAll("[data-parada]").forEach((c) => { c.disabled = !c.checked && marcadas.length >= MAX; });
    contagem.textContent = marcadas.length ? `${marcadas.length} parada${marcadas.length > 1 ? "s" : ""}${marcadas.length >= MAX ? " (máximo do mapa)" : ""}` : "Marque as concedentes do roteiro";
    botao.classList.toggle("desativado", !marcadas.length);
    document.querySelectorAll("[data-agenda-rapida-botao]").forEach((b) => { b.disabled = !marcadas.length; });
    if (!marcadas.length) { botao.removeAttribute("href"); return; }
    const destino = marcadas[marcadas.length - 1];
    const paradas = marcadas.slice(0, -1);
    const url = new URL("https://www.google.com/maps/dir/");
    url.searchParams.set("api", "1");
    url.searchParams.set("destination", destino);
    if (paradas.length) url.searchParams.set("waypoints", paradas.join("|"));
    url.searchParams.set("travelmode", "driving");
    botao.href = url.toString();
  }
  lista.addEventListener("change", atualizar);
  atualizar();
})();

// captação: marcar o curso abre o campo de vagas (sem JS, os dois aparecem e o número basta)
document.querySelectorAll("[data-curso-vaga]").forEach((caixa) => {
  const marcar = caixa.querySelector('input[type="checkbox"]');
  const qtd = caixa.querySelector("[data-qtd]");
  const numero = qtd && qtd.querySelector("input");
  if (!marcar || !qtd || !numero) return;
  if (numero.value && !marcar.checked) marcar.checked = true;
  const aplicar = (focar) => {
    qtd.hidden = !marcar.checked;
    caixa.classList.toggle("marcado", marcar.checked);
    if (!marcar.checked) numero.value = "";
    else if (focar && !numero.value) numero.focus();
  };
  marcar.addEventListener("change", () => aplicar(true));
  aplicar(false);
});
