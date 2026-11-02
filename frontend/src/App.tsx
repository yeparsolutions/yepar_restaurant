// ============================================================
// YEPAR RESTAURANT — frontend/src/App.tsx
// Decide qué pantalla ver: si no hay sesión, la entrada (login / crear restaurante);
// si hay, el panel. Solo el administrador usa el panel; el resto del equipo tendrá su pantalla de tablet.
// ============================================================
import { useEffect, useState } from "react";
import { alExpirarSesion, guardarSesion, leerSesion, type Sesion } from "./api";
import Acceso from "./Acceso";
import Panel from "./Panel";

export default function App() {
  const [sesion, setSesion] = useState<Sesion | null>(leerSesion);

  const iniciar = (s: Sesion) => {
    guardarSesion(s);
    setSesion(s);
  };
  const salir = () => {
    guardarSesion(null);
    setSesion(null);
  };
  useEffect(() => alExpirarSesion(salir), []);

  if (!sesion) return <Acceso alIniciar={iniciar} />;

  if (!sesion.usuario.roles.includes("administrador")) {
    return (
      <main className="centro">
        <div className="tarjeta">
          <Marca />
          <h1>Hola, {sesion.usuario.nombre}</h1>
          <p className="suave">
            Esta pantalla es para quien administra el restaurante. Tu pantalla de trabajo ({sesion.usuario.roles.join(", ")}) llegará
            con la app de la tablet.
          </p>
          <button className="secundario" onClick={salir}>Salir</button>
        </div>
      </main>
    );
  }
  return <Panel sesion={sesion} alSalir={salir} />;
}

export function Marca() {
  return (
    <div className="marca">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M16 2l12 7v14l-12 7-12-7V9z" fill="currentColor" />
      </svg>
      <span>Yepar Restaurant</span>
    </div>
  );
}
