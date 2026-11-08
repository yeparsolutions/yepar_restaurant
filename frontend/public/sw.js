/* ============================================================
   YEPAR RESTAURANT — public/sw.js
   Service worker: guarda la app en la tablet para que abra aunque no haya internet.
   Analogía: es la copia impresa del menú que el mesero lleva en el bolsillo.
   - Páginas: primero la red (para tener la versión nueva); si no hay red, la última copia.
   - Archivos con huella (/assets/...): primero la copia guardada (nunca cambian).
   - Nunca toca la API (otro dominio) ni peticiones que no sean GET.
   ============================================================ */
const VERSION = "yepar-v2";
const BASE = ["/", "/manifest.webmanifest", "/favicon.ico", "/icon-192.png", "/Yepar_Restaurant_Isotipo.png", "/Yepar_Restaurant_Logo.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(VERSION).then(async (c) => {
      await c.addAll(BASE);
      // También se guardan los archivos con huella que usa la página (JS y CSS), para que abra sin internet
      // desde la primera vez; si no, solo quedarían guardados los que se pidan después de instalar.
      const html = await (await fetch("/", { cache: "no-store" })).text();
      const archivos = [...new Set(html.match(/\/assets\/[^"'\s>]+/g) || [])];
      await c.addAll(archivos);
    }).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;

  // Navegación: red primero, y si falla, la página guardada.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((r) => { const copia = r.clone(); caches.open(VERSION).then((c) => c.put("/", copia)); return r; })
        .catch(() => caches.match("/")),
    );
    return;
  }

  // Archivos con huella: copia guardada primero; si no existe, se baja y se guarda.
  if (url.pathname.startsWith("/assets/")) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((r) => { const copia = r.clone(); caches.open(VERSION).then((c) => c.put(req, copia)); return r; })),
    );
    return;
  }

  // Lo demás (íconos, logo): lo guardado al instante y se refresca de fondo.
  e.respondWith(
    caches.match(req).then((hit) => {
      const red = fetch(req).then((r) => { const copia = r.clone(); caches.open(VERSION).then((c) => c.put(req, copia)); return r; }).catch(() => hit);
      return hit || red;
    }),
  );
});
