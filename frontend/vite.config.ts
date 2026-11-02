// ============================================================
// YEPAR RESTAURANT — frontend/vite.config.ts
// `vite preview` es el que sirve la web ya compilada en Railway: hay que permitirle atender
// cualquier dominio (el de Railway o el propio del cliente).
// ============================================================
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  preview: { allowedHosts: true },
});
