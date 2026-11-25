// Mapa dos estágios: um alfinete por concedente, com a cor da situação do dia. Textos montados com textContent
// (nomes vêm de cadastros, inclusive do formulário público da captação).

// O OpenStreetMap exige o endereço do site (Referer) nas imagens do mapa; a página, por padrão, não manda.
function camadaOSM() {
  return L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, referrerPolicy: "strict-origin-when-cross-origin",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  });
}

(function () {
  const area = document.querySelector("[data-mapa]");
  const fonte = document.getElementById("dados-mapa");
  if (!area || !fonte || !window.L) return;
  const locais = JSON.parse(fonte.textContent);

  const mapa = L.map(area, { scrollWheelZoom: false });
  camadaOSM().addTo(mapa);

  function el(tag, texto, classe) {
    const e = document.createElement(tag);
    if (texto) e.textContent = texto;
    if (classe) e.className = classe;
    return e;
  }

  function plural(n, um, varios) { return `${n} ${n === 1 ? um : varios}`; }

  function popup(p) {
    const caixa = el("div", "", "mapa-popup");
    const titulo = el("a", p.nome);
    titulo.href = p.url;
    const forte = el("strong");
    forte.append(titulo);
    caixa.append(forte);
    if (p.endereco) caixa.append(el("small", p.endereco));
    const n = p.contagem;
    const partes = [`${p.presentes} de ${p.total} presente${p.total === 1 ? "" : "s"}`];
    if (n.nao_chegou) partes.push(plural(n.nao_chegou, "não marcou", "não marcaram"));
    if (n.falta) partes.push(plural(n.falta, "falta", "faltas"));
    if (n.ausencia) partes.push(plural(n.ausencia, "ausência", "ausências"));
    caixa.append(el("p", partes.join(" · ")));
    caixa.append(el("p", `Supervisor: ${p.supervisor.texto}`));
    caixa.append(el("p", (p.visita ? `Visita marcada às ${p.visita} · ` : "") +
      (p.dias_sem_visita === null ? "nunca visitada" : `última visita há ${plural(p.dias_sem_visita, "dia", "dias")}`), "muted"));
    const lista = el("ul");
    p.estagiarios.forEach((e) => {
      const li = el("li");
      const a = el("a", e.nome);
      a.href = e.url;
      li.append(a, document.createTextNode(` — ${e.texto}${e.local_ok ? " · localização conferida" : ""}`));
      lista.append(li);
    });
    caixa.append(lista);
    const marcar = document.querySelector(`[data-local="${p.id}"]`);
    if (marcar) {
      const botao = el("button", "", "btn sm");
      const atualizar = () => { botao.textContent = marcar.checked ? "Tirar do roteiro" : "Incluir no roteiro"; };
      botao.type = "button";
      botao.addEventListener("click", () => { marcar.checked = !marcar.checked; marcar.dispatchEvent(new Event("change", { bubbles: true })); atualizar(); });
      atualizar();
      caixa.append(botao);
    }
    return caixa;
  }

  const pontos = [];
  locais.forEach((p) => {
    const sup = p.supervisor.presente === true ? " sup-sim" : p.supervisor.presente === false ? " sup-nao" : "";
    const icone = L.divIcon({
      className: "", iconSize: [34, 34], iconAnchor: [17, 17], popupAnchor: [0, -16],
      html: `<span class="pino ${p.cor}${sup}">${Number(p.total) || 0}</span>`,
    });
    L.marker([p.lat, p.lng], { icon: icone, title: p.nome, alt: p.nome }).addTo(mapa).bindPopup(() => popup(p), { maxWidth: 300 });
    pontos.push([p.lat, p.lng]);
  });
  if (pontos.length === 1) mapa.setView(pontos[0], 15);
  else mapa.fitBounds(pontos, { padding: [30, 30], maxZoom: 15 });

  // marcar na lista também destaca o alfinete
  document.querySelectorAll("[data-local]").forEach((c) => c.addEventListener("change", () => {
    const n = document.querySelectorAll("[data-local]:checked").length;
    const b = document.querySelector("[data-rota-botao]");
    if (b) b.lastChild.textContent = n ? ` Montar roteiro com ${n} concedente${n > 1 ? "s" : ""}` : " Montar roteiro com as marcadas";
  }));

  // página de hoje aberta: atualiza a cada 3 minutos (se ninguém estiver montando um roteiro)
  if (area.hasAttribute("data-atualizar")) {
    setInterval(() => {
      if (document.visibilityState === "visible" && !document.querySelector("[data-local]:checked") &&
          !document.querySelector(".leaflet-popup")) location.reload();
    }, 180000);
  }
})();

// Ficha da concedente: marcar o ponto no mapa (toque, arraste ou busca pelo endereço) preenche latitude e longitude.
(function () {
  const caixa = document.querySelector("[data-ponto-mapa]");
  const lat = document.getElementById("id_latitude");
  const lng = document.getElementById("id_longitude");
  if (!caixa || !lat || !lng || !window.L) return;
  const area = caixa.querySelector("[data-ponto-area]");
  const aviso = caixa.querySelector("[data-ponto-aviso]");
  const num = (v) => { const n = parseFloat(String(v).replace(",", ".")); return Number.isFinite(n) ? n : null; };
  const tem = () => num(lat.value) !== null && num(lng.value) !== null;
  const mapa = L.map(area, { scrollWheelZoom: false });
  camadaOSM().addTo(mapa);
  const icone = L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 13], html: '<span class="pino verde pino-ficha"></span>' });
  let marca = null;

  function preencher(p) {
    lat.value = Number(p.lat).toFixed(6);
    lng.value = Number(p.lng).toFixed(6);
  }
  function por(la, lo, zoom) {
    if (!marca) {
      marca = L.marker([la, lo], { icon: icone, draggable: true, title: "Arraste para ajustar" }).addTo(mapa);
      marca.on("dragend", () => preencher(marca.getLatLng()));
    } else {
      marca.setLatLng([la, lo]);
    }
    if (zoom) mapa.setView([la, lo], zoom);
  }

  const centro = (caixa.dataset.centro || "").split(",").map(Number);
  if (tem()) por(num(lat.value), num(lng.value), 17);
  else if (centro.length === 2 && centro.every(Number.isFinite)) mapa.setView(centro, 13);
  else mapa.setView([-5.2, -39.3], 7); // Ceará
  mapa.on("click", (ev) => { por(ev.latlng.lat, ev.latlng.lng); preencher(ev.latlng); });
  [lat, lng].forEach((i) => i.addEventListener("change", () => {
    if (tem()) por(num(lat.value), num(lng.value), Math.max(mapa.getZoom(), 16));
  }));

  const botao = caixa.querySelector("[data-procurar-endereco]");
  const campo = (n) => (document.getElementById("id_" + n)?.value || "").trim();
  async function procurar(consulta) {
    const url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=br&accept-language=pt-BR&q=" +
      encodeURIComponent(consulta);
    const r = await fetch(url, { referrerPolicy: "strict-origin-when-cross-origin" });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }
  botao?.addEventListener("click", async () => {
    if (!campo("cidade")) { aviso.textContent = "Preencha pelo menos a cidade do endereço."; return; }
    const rua = [campo("endereco"), campo("numero")].filter(Boolean).join(", ");
    const resto = [campo("bairro"), campo("cidade"), campo("uf"), "Brasil"].filter(Boolean).join(", ");
    botao.disabled = true;
    aviso.textContent = "Procurando…";
    try {
      let achado = rua ? (await procurar(`${rua}, ${resto}`))[0] : null;
      let preciso = Boolean(achado);
      if (!achado) achado = (await procurar(resto))[0];
      if (achado) {
        por(Number(achado.lat), Number(achado.lon), preciso ? 17 : 14);
        preencher({ lat: achado.lat, lng: achado.lon });
        aviso.textContent = preciso ? "Achamos a rua. Confira e arraste o alfinete até a entrada da concedente."
          : "Achamos só o bairro ou a cidade. Toque no mapa no ponto certo da concedente.";
      } else {
        aviso.textContent = "Endereço não encontrado. Navegue no mapa e toque no ponto da concedente.";
      }
    } catch (e) {
      aviso.textContent = "Não foi possível procurar agora. Navegue no mapa e toque no ponto da concedente.";
    }
    botao.disabled = false;
  });
})();
