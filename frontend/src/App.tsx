// ============================================================
// YEPAR RESTAURANT — frontend/src/App.tsx
// Decide qué pantalla ver: si no hay sesión, la entrada (login / crear restaurante);
// si hay, el panel. Solo el administrador usa el panel; el resto del equipo tendrá su pantalla de tablet.
// ============================================================
import { useEffect, useState } from "react";
import { alExpirarSesion, guardarSesion, guardarVinculo, leerSesion, leerVinculo, pedir, type Sesion } from "./api";
import Acceso from "./Acceso";
import Panel from "./Panel";
import Mesero from "./Mesero";

export default function App() {
  const [sesion, setSesion] = useState<Sesion | null>(leerSesion);
  const [vinculo, setVinculo] = useState<string | null>(leerVinculo);
  const [aviso, setAviso] = useState("");

  const iniciar = (s: Sesion) => {
    guardarSesion(s);
    setSesion(s);
  };
  const salir = () => {
    guardarSesion(null);
    setSesion(null);
  };
  useEffect(() => alExpirarSesion(salir), []);

  // Enlace de vinculación (#/vincular/<token>): se comprueba, se recuerda en esta tablet y se limpia la dirección.
  useEffect(() => {
    const m = /^#\/vincular\/(.+)$/.exec(location.hash);
    if (!m) return;
    const token = decodeURIComponent(m[1]);
    pedir(`/acceso/vinculo/${encodeURIComponent(token)}`, { token: "" })
      .then(() => {
        guardarVinculo(token);
        setVinculo(token);
        setAviso("¡Tablet vinculada! Desde ahora tu equipo entra tocando su nombre.");
      })
      .catch((e) => setAviso(e.message))
      .finally(() => history.replaceState(null, "", location.pathname));
  }, []);

  if (!sesion) {
    return <Acceso alIniciar={iniciar} vinculo={vinculo} aviso={aviso} alDesvincular={() => { guardarVinculo(null); setVinculo(null); }} />;
  }

  if (sesion.usuario.roles.includes("mesero") && !sesion.usuario.roles.includes("administrador")) {
    return <Mesero sesion={sesion} alSalir={salir} />;
  }
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
