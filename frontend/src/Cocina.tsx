// ============================================================
// YEPAR RESTAURANT — frontend/src/Cocina.tsx
// La pantalla de cocina y barra: las comandas llegan como "tickets" en el riel.
// Analogía: el riel de tickets de la cocina. El más antiguo va a la izquierda; el cocinero lo toma
// (Empezar), y al terminar toca la campanita (¡Lista!) para que la mesa del mesero se encienda.
// ============================================================
import { useCallback, useEffect, useRef, useState } from "react";
import { pedir, type Sesion } from "./api";
import { Marca } from "./App";
import { Dialogo } from "./Mesero";
import { BotonConteo } from "./ConteoFisico";
import { BotonRecepcion } from "./Recepcion";
import { BotonInventario, BotonRecetas } from "./CocinaApoyo";

type Comanda = {
  linea_id: string; pedido_id: string; mesa: string; plato: string; cantidad: number; estado: string;
  comensal: number | null; nota: string | null; sin: string[]; extras: string[]; enviada_en: string | null;
};
type Insumo = { item_id: number; nombre: string; agotado: boolean };

/** "hace 3 min" a partir de la hora en que se envió la comanda. */
function minutosDesde(iso: string | null, ahora: number): number {
  if (!iso) return 0;
  // La API entrega la hora en UTC; si no trae zona, se interpreta como UTC.
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return Math.max(0, Math.floor((ahora - t) / 60000));
}

export default function Cocina({ sesion, alSalir }: { sesion: Sesion; alSalir: () => void }) {
  const [comandas, setComandas] = useState<Comanda[] | null>(null);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [ahora, setAhora] = useState(Date.now());
  const [acabado, setAcabado] = useState(false);
  const vistas = useRef<Set<string> | null>(null);

  const cargar = useCallback(async () => {
    try {
      const c = await pedir<Comanda[]>("/cocina/comandas");
      // Avisa (vibración) cuando llega una comanda que no estaba en pantalla.
      const ids = new Set(c.map((x) => x.linea_id));
      if (vistas.current && c.some((x) => !vistas.current!.has(x.linea_id))) navigator.vibrate?.([300, 100, 300]);
      vistas.current = ids;
      setComandas(c);
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 5000);
    const reloj = setInterval(() => setAhora(Date.now()), 30000);
    return () => { clearInterval(t); clearInterval(reloj); };
  }, [cargar]);

  const avanzar = async (c: Comanda) => {
    setOcupado(c.linea_id);
    try {
      const r = await pedir<{ sin_stock?: string[] }>(`/cocina/lineas/${c.linea_id}/${c.estado === "enviada" ? "iniciar" : "lista"}`, { metodo: "POST" });
      setError(r?.sin_stock?.length ? `Listo, pero quedó sin stock: ${r.sin_stock.join(", ")}.` : "");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setOcupado(null);
      cargar();
    }
  };

  const esBarra = sesion.usuario.estacion === "barra";
  return (
    <>
      <header className="barra">
        <Marca />
        <span className="suave">{esBarra ? "Barra" : "Cocina"} · {sesion.usuario.nombre}</span>
        <span style={{ flex: 1 }} />
        <BotonRecetas />
        <BotonInventario />
        <BotonRecepcion />
        <BotonConteo />
        <button className="secundario" onClick={() => setAcabado(true)}>Se acabó…</button>
        <button className="secundario" onClick={alSalir}>Salir</button>
      </header>
      <main className="contenido ancho-riel">
        <h1>Comandas {comandas ? `(${comandas.length})` : ""}</h1>
        {error && <p className={error.startsWith("Listo") ? "exito" : "error"} role="alert">{error}</p>}
        {!comandas ? <p className="suave">Cargando…</p> : comandas.length === 0 ? (
          <p className="suave">Sin comandas pendientes. Cuando un mesero envíe un pedido, aparecerá aquí.</p>
        ) : (
          <div className="riel">
            {comandas.map((c) => {
              const min = minutosDesde(c.enviada_en, ahora);
              return (
                <article key={c.linea_id} className={`ticket ${c.estado} ${min >= 15 ? "tarde" : ""}`}>
                  <header><strong>{c.mesa}</strong><span className="espera">{min} min</span></header>
                  <h2>{c.cantidad}× {c.plato}</h2>
                  <ul>
                    {c.sin.map((s) => <li key={s} className="sin">SIN {s}</li>)}
                    {c.extras.map((x) => <li key={x} className="con">CON {x}</li>)}
                    {c.comensal && <li className="suave">Persona {c.comensal}</li>}
                    {c.nota && <li className="nota">“{c.nota}”</li>}
                  </ul>
                  <button disabled={ocupado === c.linea_id} onClick={() => avanzar(c)}>
                    {c.estado === "enviada" ? "Empezar" : "¡Lista!"}
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </main>
      {acabado && <SeAcabo alCerrar={() => setAcabado(false)} />}
    </>
  );
}

// ── Botón "se acabó": marca/desmarca insumos agotados ───────
function SeAcabo({ alCerrar }: { alCerrar: () => void }) {
  const [insumos, setInsumos] = useState<Insumo[] | null>(null);
  const [busca, setBusca] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const cargar = useCallback(() => pedir<Insumo[]>("/cocina/items").then(setInsumos).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); }, [cargar]);

  const alternar = async (i: Insumo) => {
    setError("");
    try {
      if (i.agotado) {
        await pedir(`/cocina/items/${i.item_id}/agotado`, { metodo: "DELETE" });
        setMsg(`${i.nombre} vuelve a estar disponible.`);
      } else {
        const r = await pedir<{ platos_agotados: string[] }>(`/cocina/items/${i.item_id}/agotado`, { metodo: "POST" });
        setMsg(r.platos_agotados.length ? `Quedan agotados para el mesero: ${r.platos_agotados.join(", ")}.` : `${i.nombre} marcado como agotado.`);
      }
    } catch (e: any) {
      setError(e.message);
    }
    cargar();
  };

  const visibles = (insumos ?? []).filter((i) => i.nombre.toLowerCase().includes(busca.trim().toLowerCase()));
  return (
    <Dialogo titulo="¿Qué se acabó?" alCerrar={alCerrar}>
      <input type="search" placeholder="Buscar ingrediente o bebida…" value={busca} onChange={(e) => setBusca(e.target.value)} aria-label="Buscar ingrediente" />
      {error && <p className="error" role="alert">{error}</p>}
      {msg && !error && <p className="exito" role="status">{msg}</p>}
      <ul className="insumos">
        {!insumos && <li className="suave">Cargando…</li>}
        {visibles.map((i) => (
          <li key={i.item_id}>
            <span>{i.nombre}</span>
            <button className={i.agotado ? "" : "secundario"} onClick={() => alternar(i)}>{i.agotado ? "Volvió" : "Se acabó"}</button>
          </li>
        ))}
      </ul>
    </Dialogo>
  );
}
