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
