// Gráfico de linha da frequência semanal (SVG simples, sem bibliotecas), com mira e dica ao passar o mouse.
(() => {
  const caixa = document.getElementById("grafico-frequencia");
  const fonte = document.getElementById("dados-tendencia");
  if (!caixa || !fonte) return;
  const dados = JSON.parse(fonte.textContent);
  const NS = "http://www.w3.org/2000/svg";
  const fmt = (v) => `${Math.round(v)}%`;
  const el = (nome, attrs, pai) => {
    const n = document.createElementNS(NS, nome);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    if (pai) pai.appendChild(n);
    return n;
  };
  let atual = null;
  const dica = document.createElement("div");
  dica.className = "dica-grafico";
  dica.hidden = true;

  function desenhar() {
    caixa.innerHTML = "";
    const W = Math.max(caixa.clientWidth, 280), H = 230;
    const m = { e: 38, d: 34, t: 14, b: 26 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" }, caixa);
    caixa.appendChild(dica);
    const x = (i) => m.e + (dados.length > 1 ? (i * (W - m.e - m.d)) / (dados.length - 1) : (W - m.e - m.d) / 2);
    const y = (v) => m.t + ((100 - v) * (H - m.t - m.b)) / 100;
    const grade = el("g", { class: "grade-y" }, svg);
    [0, 25, 50, 75, 100].forEach((v) => {
      el("line", { x1: m.e, x2: W - m.d, y1: y(v), y2: y(v) }, grade);
      const t = el("text", { x: m.e - 6, y: y(v) + 4, "text-anchor": "end" }, grade);
      t.textContent = `${v}%`;
    });
    const eixo = el("g", { class: "eixo" }, svg);
    const passo = Math.ceil(dados.length / Math.max(1, Math.floor((W - m.e - m.d) / 52)));
    dados.forEach((s, i) => {
      if (i % passo && i !== dados.length - 1) return;
      const t = el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, eixo);
      t.textContent = s.rotulo;
    });
    // linha com lacunas nas semanas sem dia de estágio
    let d = "", aberto = false;
    dados.forEach((s, i) => {
      if (s.taxa === null) { aberto = false; return; }
      d += `${aberto ? "L" : "M"}${x(i).toFixed(1)},${y(s.taxa).toFixed(1)} `;
      aberto = true;
    });
    el("path", { d, class: "linha" }, svg);
    const mira = el("line", { class: "mira", y1: m.t, y2: H - m.b, visibility: "hidden" }, svg);
    const marcas = dados.map((s, i) => (s.taxa === null ? null
      : el("circle", { cx: x(i), cy: y(s.taxa), r: 4, class: "marcador" }, svg)));
    // rótulo direto só no último ponto com valor
    let ult = -1;
    dados.forEach((s, i) => { if (s.taxa !== null) ult = i; });
    if (ult >= 0) {
      const t = el("text", { x: x(ult) + 8, y: y(dados[ult].taxa) + 4, class: "ultimo" }, svg);
      t.textContent = fmt(dados[ult].taxa);
    }
    const mostrar = (i) => {
      atual = i;
      const s = dados[i];
      marcas.forEach((c, k) => c && c.classList.toggle("ativo", k === i));
      mira.setAttribute("x1", x(i)); mira.setAttribute("x2", x(i)); mira.setAttribute("visibility", "visible");
      dica.replaceChildren();
      const forte = document.createElement("strong");
      forte.textContent = s.taxa === null ? "sem dias de estágio" : fmt(s.taxa);
      const sub = document.createElement("div");
      sub.textContent = `Semana de ${s.rotulo}${i === dados.length - 1 ? " (em curso)" : ""}`;
      dica.append(forte, sub);
      [["Presenças", `${s.presentes} de ${s.previstos}`], ["Ausências avisadas", s.avisadas], ["Faltas / sem registro", s.faltas]]
        .forEach(([r, v]) => {
          const l = document.createElement("div"); l.className = "linha-dica";
          const a = document.createElement("span"); a.textContent = r;
          const b = document.createElement("b"); b.textContent = v;
          l.append(a, b); dica.appendChild(l);
        });
      dica.hidden = false;
      const esq = Math.min(Math.max(x(i) - dica.offsetWidth / 2, 0), W - dica.offsetWidth);
      dica.style.left = `${esq}px`;
      dica.style.top = `${Math.max(0, (s.taxa === null ? m.t : y(s.taxa)) - dica.offsetHeight - 14)}px`;
    };
    const esconder = () => {
      atual = null; dica.hidden = true; mira.setAttribute("visibility", "hidden");
      marcas.forEach((c) => c && c.classList.remove("ativo"));
    };
    const area = el("rect", { x: m.e - 10, y: 0, width: W - m.e - m.d + 20, height: H, fill: "transparent" }, svg);
    const indice = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) * W) / r.width;
      let melhor = 0;
      dados.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(melhor) - px)) melhor = i; });
      return melhor;
    };
    area.addEventListener("pointermove", (ev) => mostrar(indice(ev)));
    area.addEventListener("pointerdown", (ev) => mostrar(indice(ev)));
    area.addEventListener("pointerleave", esconder);
    caixa.onkeydown = (ev) => {
      if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
        ev.preventDefault();
        const i = atual === null ? dados.length - 1 : atual + (ev.key === "ArrowRight" ? 1 : -1);
        mostrar(Math.min(Math.max(i, 0), dados.length - 1));
      } else if (ev.key === "Escape") esconder();
    };
    caixa.onfocus = () => { if (atual === null) mostrar(dados.length - 1); };
    caixa.onblur = esconder;
  }
  desenhar();
  let espera;
  window.addEventListener("resize", () => { clearTimeout(espera); espera = setTimeout(desenhar, 120); });
})();
// filtros: aplicam ao mudar
document.querySelectorAll("form[data-autoenvio] select").forEach((s) => s.addEventListener("change", () => s.form.submit()));
