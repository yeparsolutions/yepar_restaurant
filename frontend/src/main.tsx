import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./estilos.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Service worker: deja la app guardada en la tablet para abrirla sin internet (solo en la versión publicada).
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* sin service worker la app funciona igual; solo no abre sin internet */
    });
  });
}
