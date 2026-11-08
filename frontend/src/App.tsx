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
import Cocina from "./Cocina";
import { fijarMoneda } from "./dinero";
import Caja from "./Caja";

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

  // La moneda del restaurante decide cómo se ven los montos ($, Bs., US$…). Se pide al entrar; sin red se usa la última guardada.
  const [, setMoneda] = useState(0);
  useEffect(() => {
    if (!sesion) return;
    pedir<{ moneda: string }>("/auth/empresa").then((e) => { fijarMoneda(e.moneda); setMoneda((n) => n + 1); }).catch(() => {});
  }, [sesion?.access_token]);

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
  if (sesion.usuario.roles.includes("cocinero") && !sesion.usuario.roles.includes("administrador")) {
    return <Cocina sesion={sesion} alSalir={salir} />;
  }
  if (sesion.usuario.roles.includes("cajero") && !sesion.usuario.roles.includes("administrador")) {
    return <Caja sesion={sesion} alSalir={salir} />;
  }
  if (!sesion.usuario.roles.includes("administrador")) {
    return (
      <main className="centro">
        <div className="tarjeta">
          <Marca grande />
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

/** La marca de Yepar Restaurant. Compacta (isotipo + nombre) en las barras; `grande` muestra el logo completo en las tarjetas de entrada. */
export function Marca({ grande = false }: { grande?: boolean }) {
  if (grande) {
    return (
      <div className="marca marca-grande">
        <img src="/Yepar_Restaurant_Logo.png" alt="Yepar Restaurant — Gestión integral para tu restaurant" />
      </div>
    );
  }
  return (
    <div className="marca">
      <img src="/Yepar_Restaurant_Isotipo.png" alt="" width="26" height="31" />
      <span>Yepar Restaurant</span>
    </div>
  );
}
