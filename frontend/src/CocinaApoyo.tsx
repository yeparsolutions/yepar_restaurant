// ============================================================
// YEPAR RESTAURANT — frontend/src/CocinaApoyo.tsx
// Lo que el cocinero consulta entre comandas: el recetario y el inventario (sin costos).
// Analogía: el cuaderno de recetas colgado junto a la cocina y la libreta de la bodega. Un cocinero nuevo
// los abre para saber cómo se arma cada plato, qué hay en el estante y qué falta reponer.
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { pedir } from "./api";
import { Dialogo } from "./Mesero";

const cant = (v: string | number) => Number(v).toLocaleString("es", { maximumFractionDigits: 3 });
const MOTIVOS: [string, string][] = [["vencido", "Vencido"], ["danado", "Dañado"], ["error_preparacion", "Error de preparación"], ["sobrante", "Sobrante"], ["derrame", "Derrame"]];
const TIPOS: Record<string, string> = { materia_prima: "Materia prima", componente: "Preparación", vendible_reventa: "Reventa", vendible_preparado: "Plato" };

// ── Recetario ────────────────────────────────────────────────
type FilaReceta = { item_id: number; nombre: string; tipo: string };
type Receta = { nombre: string; rendimiento: string; unidad: string; instrucciones: string | null; lineas: { ingrediente_id: number; nombre: string; cantidad: string; unidad: string; es_removible: boolean }[] };

export function BotonRecetas() {
  const [abierto, setAbierto] = useState(false);
  return (
    <>
      <button className="secundario" onClick={() => setAbierto(true)}>Recetas</button>
      {abierto && <Recetario alCerrar={() => setAbierto(false)} />}
    </>
  );
}

function Recetario({ alCerrar }: { alCerrar: () => void }) {
  const [lista, setLista] = useState<FilaReceta[] | null>(null);
  const [receta, setReceta] = useState<Receta | null>(null);
  const [busca, setBusca] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { pedir<FilaReceta[]>("/cocina/recetas").then(setLista).catch((e) => setError(e.message)); }, []);
  const abrir = async (f: FilaReceta) => {
    setError("");
    try { setReceta(await pedir<Receta>(`/items/${f.item_id}/receta`)); } catch (e: any) { setError(e.message); }
  };
  const visibles = (lista ?? []).filter((f) => f.nombre.toLowerCase().includes(busca.trim().toLowerCase()));
  return (
    <Dialogo titulo={receta ? receta.nombre : "Recetas"} alCerrar={alCerrar}>
      {error && <p className="error" role="alert">{error}</p>}
      {receta ? (
        <div style={{ display: "grid", gap: 8 }}>
          <p className="suave">Rinde {cant(receta.rendimiento)} {receta.unidad}.</p>
          <ul className="lineas">
            {receta.lineas.map((l) => (
              <li key={l.ingrediente_id} className="linea">
                <span>{l.nombre}{l.es_removible && <small className="suave"> · se puede quitar</small>}</span>
                <strong>{cant(l.cantidad)} {l.unidad}</strong>
              </li>
            ))}
          </ul>
          {receta.instrucciones && <p style={{ whiteSpace: "pre-wrap" }}>{receta.instrucciones}</p>}
          <button className="secundario" onClick={() => setReceta(null)}>← Todas las recetas</button>
        </div>
      ) : !lista ? <p className="suave">Cargando…</p> : lista.length === 0 ? (
        <p className="suave">Todavía no hay recetas cargadas. El administrador las crea en Panel → Platos.</p>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          <input type="search" placeholder="Buscar plato…" aria-label="Buscar receta" value={busca} onChange={(e) => setBusca(e.target.value)} />
          <ul className="lineas">
            {visibles.map((f) => (
              <li key={f.item_id} className="linea">
                <div><strong>{f.nombre}</strong><div className="suave">{TIPOS[f.tipo] ?? f.tipo}</div></div>
                <button onClick={() => abrir(f)}>Ver</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Dialogo>
  );
}

// ── Inventario (stock, faltantes y mermas; sin costos) ───────
type Stock = { item_id: number; nombre: string; tipo: string; unidad: string; fisico: string; reservado: string; disponible: string; stock_minimo: string };
type Alerta = { item_id: number; nombre: string; disponible: string; stock_minimo: string; unidad: string; se_produce: boolean };

export function BotonInventario() {
  const [abierto, setAbierto] = useState(false);
  return (
    <>
      <button className="secundario" onClick={() => setAbierto(true)}>Inventario</button>
      {abierto && <InventarioCocina alCerrar={() => setAbierto(false)} />}
    </>
  );
}

function InventarioCocina({ alCerrar }: { alCerrar: () => void }) {
  const [vista, setVista] = useState<"stock" | "faltan">("stock");
  const [stock, setStock] = useState<Stock[] | null>(null);
  const [alertas, setAlertas] = useState<Alerta[] | null>(null);
  const [merma, setMerma] = useState<Stock | null>(null);
  const [busca, setBusca] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const cargar = useCallback(() => {
    pedir<Stock[]>("/inventario/stock").then(setStock).catch((e) => setError(e.message));
    pedir<Alerta[]>("/inventario/alertas").then(setAlertas).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { cargar(); }, [cargar]);

  const visibles = (stock ?? []).filter((f) => f.nombre.toLowerCase().includes(busca.trim().toLowerCase()));
  return (
    <Dialogo titulo="Inventario" alCerrar={alCerrar}>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <button className={vista === "stock" ? "" : "secundario"} onClick={() => setVista("stock")}>Lo que hay</button>
        <button className={vista === "faltan" ? "" : "secundario"} onClick={() => setVista("faltan")}>Lo que falta{alertas?.length ? ` (${alertas.length})` : ""}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="exito" role="status">{aviso}</p>}
      {vista === "stock" ? (
        !stock ? <p className="suave">Cargando…</p> : (
          <div style={{ display: "grid", gap: 8 }}>
            <input type="search" placeholder="Buscar ítem…" aria-label="Buscar ítem" value={busca} onChange={(e) => setBusca(e.target.value)} />
            <ul className="lineas">
              {visibles.map((f) => (
                <li key={f.item_id} className="linea">
                  <div><strong>{f.nombre}</strong><div className="suave">{cant(f.disponible)} {f.unidad} disponibles · mínimo {cant(f.stock_minimo)}</div></div>
                  <button className="secundario" onClick={() => { setAviso(""); setMerma(f); }}>Merma</button>
                </li>
              ))}
            </ul>
          </div>
        )
      ) : !alertas ? <p className="suave">Cargando…</p> : alertas.length === 0 ? (
        <p className="suave">No falta nada: todo está sobre su mínimo.</p>
      ) : (
        <ul className="lineas">
          {alertas.map((a) => (
            <li key={a.item_id} className="linea">
              <div><strong>{a.nombre}</strong><div className="suave">Quedan {cant(a.disponible)} {a.unidad} · mínimo {cant(a.stock_minimo)}{a.se_produce ? " · se prepara en cocina" : ""}</div></div>
            </li>
          ))}
        </ul>
      )}
      {merma && <DialogoMerma fila={merma} alCerrar={() => setMerma(null)} alTerminar={(m) => { setMerma(null); setAviso(m); cargar(); }} />}
    </Dialogo>
  );
}

function DialogoMerma({ fila, alCerrar, alTerminar }: { fila: Stock; alCerrar: () => void; alTerminar: (m: string) => void }) {
  const [cantidad, setCantidad] = useState("");
  const [motivo, setMotivo] = useState("vencido");
  const [nota, setNota] = useState("");
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError(""); setOcupado(true);
    try {
      const r = await pedir<{ stock_nuevo: string }>("/inventario/mermas", { json: { item_id: fila.item_id, cantidad, motivo, nota: nota.trim() || null } });
      alTerminar(`Merma anotada: ${cant(cantidad)} ${fila.unidad} de ${fila.nombre}. Quedan ${cant(r.stock_nuevo)} ${fila.unidad}.`);
    } catch (e: any) { setError(e.message); } finally { setOcupado(false); }
  };
  return (
    <Dialogo titulo={`Anotar merma · ${fila.nombre}`} alCerrar={alCerrar}>
      <form onSubmit={enviar} style={{ display: "grid", gap: 8 }}>
        <label className="campo"><span>Cantidad ({fila.unidad})</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={cantidad} onChange={(e) => setCantidad(e.target.value)} required autoFocus />
        </label>
        <label className="campo"><span>Motivo</span>
          <select value={motivo} onChange={(e) => setMotivo(e.target.value)}>{MOTIVOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
        </label>
        <label className="campo"><span>Nota (opcional)</span><input value={nota} onChange={(e) => setNota(e.target.value)} maxLength={255} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={ocupado || !cantidad}>Anotar merma</button>
      </form>
    </Dialogo>
  );
}
