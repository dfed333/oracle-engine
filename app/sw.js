/* Oracle Engine — service worker
   - app e dati restano sul telefono: funziona anche senza internet
   - pagina e dati: prima la rete, chiedendo sempre al server se ci sono novità
     (scavalca la memoria del browser), poi la copia salvata se non c'è rete
   - VERSIONE cambia a ogni pubblicazione: il telefono installa da solo la nuova
     versione e l'app si ricarica (vedi index.html, "aggiornamento automatico") */
const VERSIONE = "__VERSIONE__";
const CACHE = "oracle-" + VERSIONE;
const BASE = ["./", "./index.html", "./data.json", "./manifest.webmanifest",
              "./icon-192.png", "./icon-512.png", "./icon-maskable-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE)
    .then(c => c.addAll(BASE.map(u => new Request(u, {cache: "reload"}))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(k => Promise.all(k.filter(x => x.startsWith("oracle-") && x !== CACHE).map(x => caches.delete(x))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const fontEsterno = url.hostname.endsWith("googleapis.com") || url.hostname.endsWith("gstatic.com");
  const daAggiornare = req.mode === "navigate" || url.pathname.endsWith("/data.json") ||
                       url.pathname.endsWith("/index.html") || url.pathname.endsWith("/");
  if (daAggiornare && url.origin === location.origin) {
    e.respondWith(fetch(url.href, {cache: "no-cache", credentials: "same-origin"}).then(res => {
      if (res.ok) { const copia = res.clone(); caches.open(CACHE).then(c => c.put(req, copia)); }
      return res;
    }).catch(() => caches.match(req, {ignoreSearch: true}).then(r => r || caches.match("./index.html"))));
    return;
  }
  if (url.origin === location.origin || fontEsterno) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok || res.type === "opaque") { const copia = res.clone(); caches.open(CACHE).then(c => c.put(req, copia)); }
      return res;
    })));
  }
});
