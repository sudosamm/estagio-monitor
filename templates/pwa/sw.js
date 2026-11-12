// Service worker do {{ NOME_SISTEMA }}. Gerado pelo servidor: a lista de arquivos muda a cada deploy.
const CACHE = "em-{{ versao }}";
const ARQUIVOS = [{% for a in arquivos %}"{{ a|escapejs }}", {% endfor %}"/offline/"];

self.addEventListener("install", (ev) => {
  ev.waitUntil(caches.open(CACHE).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys().then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (ev) => {
  const req = ev.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // páginas: sempre da rede (dados atualizados e nada pessoal guardado); sem conexão, a página offline
  if (req.mode === "navigate") {
    ev.respondWith(fetch(req).catch(() => caches.match("/offline/")));
    return;
  }
  // arquivos estáticos: do cache primeiro (em produção os nomes mudam a cada versão)
  if (url.pathname.startsWith("/static/")) {
    {% if rede_primeiro %}ev.respondWith(fetch(req).catch(() => caches.match(req)));
    return;{% endif %}
    ev.respondWith(caches.match(req).then((r) => r || fetch(req).then((resp) => {
      if (resp.ok) { const copia = resp.clone(); caches.open(CACHE).then((c) => c.put(req, copia)); }
      return resp;
    })));
  }
});

// notificações no celular: mostra o aviso e, ao tocar, abre a página certa
self.addEventListener("push", (ev) => {
  let d = {};
  try { d = ev.data ? ev.data.json() : {}; } catch (e) { d = { texto: ev.data ? ev.data.text() : "" }; }
  ev.waitUntil(self.registration.showNotification(d.titulo || "{{ NOME_SISTEMA|escapejs }}", {
    body: d.texto || "", icon: "{{ icone|escapejs }}", badge: "{{ icone|escapejs }}", lang: "pt-BR",
    tag: d.tag || undefined, data: { url: d.url || "/" },
  }));
});
self.addEventListener("notificationclick", (ev) => {
  ev.notification.close();
  const url = new URL((ev.notification.data && ev.notification.data.url) || "/", self.location.origin).href;
  ev.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((janelas) => {
    for (const j of janelas) {
      if (j.url.startsWith(self.location.origin) && "navigate" in j) return j.navigate(url).then((w) => w && w.focus());
    }
    return self.clients.openWindow(url);
  }));
});
