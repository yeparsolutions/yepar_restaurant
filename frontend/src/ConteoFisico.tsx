// ============================================================
// YEPAR RESTAURANT — frontend/src/ConteoFisico.tsx
// Inventario físico a ciegas: el administrador lo abre y lo revisa; el cocinero cuenta sin ver el stock del sistema.
// Analogía: el arqueo de la bodega. Quien cuenta no sabe cuánto "debería" haber, así no puede cuadrar el conteo
// por costumbre. Recién cuando termina, el administrador compara y decide si ajusta el stock a lo contado.
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { pedir } from "./api";
import { plata } from "./dinero";
import { Dialogo } from "./Mesero";

type Resumen = { id: number; estado: string; categoria_id: number | null; nota: string | null; total_items: number; contados: number };
type Categoria = { id: number; nombre: string };
type LineaRev = { item_id: number; item: string; unidad_base: string; cantidad_sistema: string; cantidad_contada: string | null; diferencia: string; valor_diferencia: string };
type Revision = { id: number; estado: string; lineas: LineaRev[]; con_diferencia: number; valor_total_diferencia: string };
type Presentacion = { id: number; nombre: string };
type LineaCiega = { item_id: number; item: string; unidad_base: string; presentaciones: Presentacion[]; contada: string | null };
type Hoja = { id: number; estado: string; total_items: number; contados: number; lineas: LineaCiega[] };

const ESTADO: Record<string, string> = { contando: "Contando", en_revision: "En revisión", cerrado: "Cerrado", cancelado: "Cancelado" };
const cant = (v: string | number) => Number(v).toLocaleString("es", { maximumFractionDigits: 3 });
const signo = (v: string | number) => (Number(v) > 0 ? "+" : "") + cant(v);

// ── Administrador ───────────────────────────────────────────
export default function ConteoFisico() {
  const [lista, setLista] = useState<Resumen[] | null>(null);
  const [categorias, setCategorias] = useState<Categoria[]>([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [categoria, setCategoria] = useState("");
  const [nota, setNota] = useState("");
  const [revisando, setRevisando] = useState<Resumen | null>(null);
  const cargar = useCallback(() => pedir<Resumen[]>("/inventario-fisico").then((l) => { setLista(l); setError(""); }).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); pedir<Categoria[]>("/categorias").then(setCategorias).catch(() => {}); }, [cargar]);
  // Mientras el cocinero cuenta, el avance se refresca solo.
  useEffect(() => { const t = setInterval(cargar, 10000); return () => clearInterval(t); }, [cargar]);

  const activo = (lista ?? []).find((i) => i.estado === "contando" || i.estado === "en_revision");
  const historial = (lista ?? []).filter((i) => i !== activo);
  const nombreCat = (id: number | null) => (id === null ? "Todo el inventario" : categorias.find((c) => c.id === id)?.nombre ?? `Categoría ${id}`);

  const accion = async (ruta: string, msg: string) => {
    setError(""); setAviso("");
    try { await pedir(ruta, { metodo: "POST" }); setAviso(msg); } catch (e: any) { setError(e.message); }
    cargar();
  };
  const abrir = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError(""); setAviso("");
    try {
      await pedir("/inventario-fisico", { json: { categoria_id: categoria ? Number(categoria) : null, nota: nota.trim() || null } });
      setAviso("Conteo abierto: el cocinero lo verá en su pantalla."); setNota("");
    } catch (e: any) { setError(e.message); }
    cargar();
  };

  return (
    <>
      <div className="encabezado"><h1>Conteo de inventario</h1></div>
      <p className="suave">El cocinero cuenta sin ver cuánto dice el sistema. Al terminar, tú comparas y decides si ajustas el stock.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="exito" role="status">{aviso}</p>}
      {!lista ? <p className="suave">Cargando…</p> : activo ? (
        <div className="formulario">
          <h2 style={{ marginTop: 0 }}>{nombreCat(activo.categoria_id)} <span className="chip">{ESTADO[activo.estado]}</span></h2>
          {activo.nota && <p className="suave">{activo.nota}</p>}
          <p>Contados: <strong>{activo.contados} de {activo.total_items}</strong></p>
          <div className="progreso"><div style={{ width: `${activo.total_items ? (100 * activo.contados) / activo.total_items : 0}%` }} /></div>
          <div className="acciones">
            {activo.estado === "en_revision" && <button onClick={() => setRevisando(activo)}>Revisar diferencias</button>}
            <button className="secundario" onClick={() => confirm("¿Cancelar este conteo? El stock no se toca.") && accion(`/inventario-fisico/${activo.id}/cancelar`, "Conteo cancelado.")}>Cancelar conteo</button>
          </div>
        </div>
      ) : (
        <form className="formulario" onSubmit={abrir} style={{ maxWidth: 480 }}>
          <h2 style={{ marginTop: 0 }}>Abrir un conteo</h2>
          <label className="campo"><span>Qué contar</span>
            <select value={categoria} onChange={(e) => setCategoria(e.target.value)}>
              <option value="">Todo el inventario</option>
              {categorias.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select>
          </label>
          <label className="campo"><span>Nota (opcional)</span><input value={nota} onChange={(e) => setNota(e.target.value)} maxLength={500} placeholder="Ej.: cierre de mes" /></label>
          <button type="submit">Abrir conteo</button>
        </form>
      )}

      {historial.length > 0 && (
        <>
          <h2>Anteriores</h2>
          <ul className="lineas">
            {historial.slice(0, 10).map((i) => (
              <li key={i.id} className="linea">
                <div><strong>{nombreCat(i.categoria_id)}</strong>{i.nota ? ` · ${i.nota}` : ""}<div className="suave">{i.total_items} ítems</div></div>
                <span className="chip">{ESTADO[i.estado] ?? i.estado}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {revisando && <RevisionConteo inv={revisando} alCerrar={() => setRevisando(null)} alTerminar={(m) => { setRevisando(null); setAviso(m); cargar(); }} />}
    </>
  );
}

function RevisionConteo({ inv, alCerrar, alTerminar }: { inv: Resumen; alCerrar: () => void; alTerminar: (mensaje: string) => void }) {
  const [rev, setRev] = useState<Revision | null>(null);
  const [marcados, setMarcados] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => { pedir<Revision>(`/inventario-fisico/${inv.id}/revision`).then(setRev).catch((e) => setError(e.message)); }, [inv.id]);
  const alternar = (id: number) => setMarcados((m) => { const n = new Set(m); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const recontar = async () => {
    setError(""); setOcupado(true);
    try {
      await pedir(`/inventario-fisico/${inv.id}/recontar`, { json: { item_ids: [...marcados] } });
      alTerminar(`Se pidió recontar ${marcados.size} ítem${marcados.size === 1 ? "" : "s"}: el cocinero los verá en su pantalla.`);
    } catch (e: any) { setError(e.message); } finally { setOcupado(false); }
  };
  const cerrar = async () => {
    if (!rev || !confirm(`Se ajustará el stock de ${rev.con_diferencia} ítem${rev.con_diferencia === 1 ? "" : "s"} a lo contado. ¿Cerrar el inventario?`)) return;
    setError(""); setOcupado(true);
    try {
      const r = await pedir<{ ajustes: number }>(`/inventario-fisico/${inv.id}/cerrar`, { metodo: "POST" });
      alTerminar(`Inventario cerrado: ${r.ajustes} ajuste${r.ajustes === 1 ? "" : "s"} de stock.`);
    } catch (e: any) { setError(e.message); } finally { setOcupado(false); }
  };

  return (
    <Dialogo titulo="Diferencias del conteo" alCerrar={alCerrar}>
      {error && <p className="error" role="alert">{error}</p>}
      {!rev ? <p className="suave">Cargando…</p> : (
        <>
          <p>{rev.con_diferencia === 0 ? "El conteo calza con el sistema." : <>Hay <strong>{rev.con_diferencia}</strong> ítem{rev.con_diferencia === 1 ? "" : "s"} con diferencia · valor total <strong>{plata(rev.valor_total_diferencia)}</strong></>}</p>
          <div className="tabla-scroll">
            <table>
              <thead><tr><th /><th>Ítem</th><th>Sistema</th><th>Contado</th><th>Diferencia</th><th>Valor</th></tr></thead>
              <tbody>
                {rev.lineas.map((l) => {
                  const dif = Number(l.diferencia) !== 0;
                  return (
                    <tr key={l.item_id} className={dif ? "fila-alerta" : undefined}>
                      <td><input type="checkbox" aria-label={`Recontar ${l.item}`} checked={marcados.has(l.item_id)} onChange={() => alternar(l.item_id)} /></td>
                      <td><strong>{l.item}</strong></td>
                      <td>{cant(l.cantidad_sistema)} {l.unidad_base}</td>
                      <td>{l.cantidad_contada === null ? "—" : `${cant(l.cantidad_contada)} ${l.unidad_base}`}</td>
                      <td>{dif ? `${signo(l.diferencia)} ${l.unidad_base}` : "—"}</td>
                      <td>{dif ? plata(l.valor_diferencia) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="acciones">
            <button className="secundario" disabled={ocupado || marcados.size === 0} onClick={recontar}>Pedir recuento ({marcados.size})</button>
            <button disabled={ocupado} onClick={cerrar}>Cerrar y ajustar stock</button>
          </div>
        </>
      )}
    </Dialogo>
  );
}

// ── Cocinero ────────────────────────────────────────────────
/** Botón de la pantalla de cocina: aparece cuando el administrador abrió un conteo. */
export function BotonConteo() {
  const [hay, setHay] = useState(false);
  const [abierto, setAbierto] = useState(false);
  const [aviso, setAviso] = useState("");
  const revisar = useCallback(() => pedir<Hoja>("/inventario-fisico/activo").then(() => setHay(true)).catch(() => setHay(false)), []);
  useEffect(() => { revisar(); const t = setInterval(revisar, 30000); return () => clearInterval(t); }, [revisar]);
  return (
    <>
      <button className="secundario" onClick={() => { setAviso(""); setAbierto(true); }}>Contar inventario{hay ? " (abierto)" : ""}</button>
      {aviso && <span className="exito" role="status" style={{ padding: "4px 10px", borderRadius: 8 }}>{aviso}</span>}
      {abierto && <HojaConteo alCerrar={() => { setAbierto(false); revisar(); }} alTerminar={(m) => { setAbierto(false); setAviso(m); revisar(); }} />}
    </>
  );
}

function HojaConteo({ alCerrar, alTerminar }: { alCerrar: () => void; alTerminar: (mensaje: string) => void }) {
  const [hoja, setHoja] = useState<Hoja | null>(null);
  const [valores, setValores] = useState<Record<number, { cantidad: string; unidad: string }>>({});
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState<number | null>(null);
  const [busca, setBusca] = useState("");
  useEffect(() => { pedir<Hoja>("/inventario-fisico/activo").then(setHoja).catch((e) => setError(e.message)); }, []);

  const poner = (id: number, parcial: Partial<{ cantidad: string; unidad: string }>) =>
    setValores((v) => ({ ...v, [id]: { ...{ cantidad: "", unidad: "" }, ...v[id], ...parcial } }));
  const guardar = async (l: LineaCiega) => {
    if (!hoja) return;
    const v = valores[l.item_id];
    if (!v || v.cantidad === "") return;
    setError(""); setGuardando(l.item_id);
    try {
      setHoja(await pedir<Hoja>(`/inventario-fisico/${hoja.id}/contar`, {
        json: { item_id: l.item_id, cantidad: v.cantidad, ...(v.unidad ? { presentacion_id: Number(v.unidad) } : { unidad: l.unidad_base }) },
      }));
      setValores((x) => { const n = { ...x }; delete n[l.item_id]; return n; });
    } catch (e: any) { setError(e.message); } finally { setGuardando(null); }
  };
  const terminar = async () => {
    if (!hoja) return;
    setError("");
    try { await pedir(`/inventario-fisico/${hoja.id}/finalizar-conteo`, { metodo: "POST" }); alTerminar("Conteo enviado al administrador."); } catch (e: any) { setError(e.message); }
  };

  const visibles = (hoja?.lineas ?? []).filter((l) => l.item.toLowerCase().includes(busca.trim().toLowerCase()));
  return (
    <Dialogo titulo={hoja ? `Contar inventario (${hoja.contados}/${hoja.total_items})` : "Contar inventario"} alCerrar={alCerrar}>
      {error && hoja && <p className="error" role="alert">{error}</p>}
      {!hoja ? <p className="suave">{error ? "No hay un conteo abierto. Cuando el administrador inicie un inventario, podrás contar aquí." : "Cargando…"}</p> : (
        <div style={{ display: "grid", gap: 8 }}>
          <p className="suave">Cuenta lo que hay en el estante y anota cada ítem. Si no hay nada, escribe 0.</p>
          <input type="search" placeholder="Buscar ítem…" aria-label="Buscar ítem" value={busca} onChange={(e) => setBusca(e.target.value)} />
          {visibles.map((l) => (
            <div key={l.item_id} className="linea-factura">
              <strong>{l.item}{l.contada !== null && <span className="suave"> ✓ {cant(l.contada)} {l.unidad_base}</span>}</strong>
              <input type="number" inputMode="decimal" min="0" step="any" placeholder="Cantidad" aria-label={`Cantidad contada de ${l.item}`}
                value={valores[l.item_id]?.cantidad ?? ""} onChange={(e) => poner(l.item_id, { cantidad: e.target.value })} />
              <select aria-label={`Unidad de ${l.item}`} value={valores[l.item_id]?.unidad ?? ""} onChange={(e) => poner(l.item_id, { unidad: e.target.value })}>
                <option value="">{l.unidad_base}</option>
                {l.presentaciones.map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
              </select>
              <button className="secundario" disabled={guardando === l.item_id || !(valores[l.item_id]?.cantidad)} onClick={() => guardar(l)}>{l.contada !== null ? "Corregir" : "Anotar"}</button>
            </div>
          ))}
          <button disabled={hoja.contados < hoja.total_items} onClick={terminar}>
            {hoja.contados < hoja.total_items ? `Faltan ${hoja.total_items - hoja.contados} por contar` : "Terminar conteo"}
          </button>
        </div>
      )}
    </Dialogo>
  );
}
