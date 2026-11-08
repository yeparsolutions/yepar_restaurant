// ============================================================
// YEPAR RESTAURANT — frontend/src/Compras.tsx
// Facturas de compra del administrador: registra lo que dice la factura del proveedor y, cuando el cocinero
// cuenta lo que llegó, compara una cosa con la otra.
// Analogía: la puerta de la bodega con dos llaves. La primera la gira el administrador (anota la factura);
// la segunda, el cocinero (cuenta a ciegas lo que llegó). El stock solo sube cuando se giran las dos.
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { pedir } from "./api";
import { plata } from "./dinero";
import { Dialogo } from "./Mesero";

type Resumen = { id: number; proveedor: string; numero_documento: string | null; estado: string; lineas: number };
type LineaC = { id: number; item: string; unidad_base: string; cantidad_facturada: string; costo_unitario_base: string; cantidad_recibida: string | null; diferencia: string | null };
type Compra = { id: number; proveedor: string; numero_documento: string | null; estado: string; nota: string | null; lineas: LineaC[] };
type ItemStock = { item_id: number; nombre: string; tipo: string; unidad: string };
type LineaForm = { item_id: string; cantidad: string; monto: string };

const ESTADO: Record<string, string> = { por_recibir: "Por recibir", recibida: "Recibida", anulada: "Anulada" };
const cant = (v: string | number) => Number(v).toLocaleString("es", { maximumFractionDigits: 3 });

export default function Compras() {
  const [lista, setLista] = useState<Resumen[] | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [nueva, setNueva] = useState(false);
  const [ver, setVer] = useState<number | null>(null);
  const cargar = useCallback(() => pedir<Resumen[]>("/compras").then((l) => { setLista(l); setError(""); }).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); }, [cargar]);

  return (
    <>
      <div className="encabezado">
        <h1>Compras</h1>
        <button onClick={() => { setAviso(""); setNueva(true); }}>Registrar factura</button>
      </div>
      <p className="suave">Anota la factura del proveedor. El stock sube cuando el cocinero cuenta lo que llegó (recepción a ciegas).</p>
      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="exito" role="status">{aviso}</p>}
      {!lista ? <p className="suave">Cargando…</p> : lista.length === 0 ? <p className="suave">Todavía no hay facturas de compra.</p> : (
        <ul className="lineas">
          {lista.map((c) => (
            <li key={c.id} className="linea">
              <div>
                <strong>{c.proveedor}</strong>{c.numero_documento ? ` · N° ${c.numero_documento}` : ""}
                <div className="suave">{c.lineas} línea{c.lineas === 1 ? "" : "s"}</div>
              </div>
              <span className="chip">{ESTADO[c.estado] ?? c.estado}</span>
              <button className="secundario" onClick={() => setVer(c.id)}>Ver</button>
            </li>
          ))}
        </ul>
      )}
      {nueva && <NuevaFactura alCerrar={() => setNueva(false)} alTerminar={(m) => { setNueva(false); setAviso(m); cargar(); }} />}
      {ver !== null && <DetalleCompra id={ver} alCerrar={() => setVer(null)} alCambiar={(m) => { setVer(null); setAviso(m); cargar(); }} />}
    </>
  );
}

function NuevaFactura({ alCerrar, alTerminar }: { alCerrar: () => void; alTerminar: (mensaje: string) => void }) {
  const [items, setItems] = useState<ItemStock[]>([]);
  const [proveedor, setProveedor] = useState("");
  const [numero, setNumero] = useState("");
  const [nota, setNota] = useState("");
  const [lineas, setLineas] = useState<LineaForm[]>([{ item_id: "", cantidad: "", monto: "" }]);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => {
    // Se compra lo que no se vende preparado: materia prima, preparaciones y productos de reventa.
    pedir<ItemStock[]>("/inventario/stock").then((s) => setItems(s.filter((i) => i.tipo !== "vendible_preparado"))).catch((e) => setError(e.message));
  }, []);
  const unidad = (id: string) => items.find((i) => String(i.item_id) === id)?.unidad ?? "";
  const cambiar = (n: number, parcial: Partial<LineaForm>) => setLineas((ls) => ls.map((l, i) => (i === n ? { ...l, ...parcial } : l)));
  const total = lineas.reduce((s, l) => s + Number(l.monto || 0), 0);
  const completas = lineas.every((l) => l.item_id && Number(l.cantidad) > 0 && l.monto !== "");

  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError(""); setOcupado(true);
    try {
      await pedir("/compras", {
        json: {
          proveedor: proveedor.trim(), numero_documento: numero.trim() || null, nota: nota.trim() || null,
          lineas: lineas.map((l) => ({ item_id: Number(l.item_id), cantidad: l.cantidad, unidad: unidad(l.item_id), monto_neto: l.monto })),
        },
      });
      alTerminar(`Factura de ${proveedor.trim()} registrada. Queda por recibir: avisa al cocinero.`);
    } catch (e: any) { setError(e.message); } finally { setOcupado(false); }
  };

  return (
    <Dialogo titulo="Registrar factura de compra" alCerrar={alCerrar}>
      <form onSubmit={enviar} style={{ display: "grid", gap: 8 }}>
        <label className="campo"><span>Proveedor</span><input value={proveedor} onChange={(e) => setProveedor(e.target.value)} required maxLength={120} autoFocus /></label>
        <label className="campo"><span>N° de documento (opcional)</span><input value={numero} onChange={(e) => setNumero(e.target.value)} maxLength={60} /></label>
        <h3 style={{ margin: "8px 0 0" }}>Lo que dice la factura</h3>
        {lineas.map((l, n) => (
          <div key={n} className="linea-factura">
            <select aria-label={`Ítem de la línea ${n + 1}`} value={l.item_id} onChange={(e) => cambiar(n, { item_id: e.target.value })} required>
              <option value="">Elige un ítem…</option>
              {items.map((i) => <option key={i.item_id} value={i.item_id}>{i.nombre}</option>)}
            </select>
            <input type="number" inputMode="decimal" min="0" step="any" placeholder={`Cantidad${unidad(l.item_id) ? ` (${unidad(l.item_id)})` : ""}`}
              aria-label={`Cantidad de la línea ${n + 1}`} value={l.cantidad} onChange={(e) => cambiar(n, { cantidad: e.target.value })} required />
            <input type="number" inputMode="decimal" min="0" step="any" placeholder="Monto neto" aria-label={`Monto neto de la línea ${n + 1}`}
              value={l.monto} onChange={(e) => cambiar(n, { monto: e.target.value })} required />
            {lineas.length > 1 && <button type="button" className="secundario" aria-label={`Quitar línea ${n + 1}`} onClick={() => setLineas((ls) => ls.filter((_, i) => i !== n))}>✕</button>}
          </div>
        ))}
        <button type="button" className="secundario" onClick={() => setLineas((ls) => [...ls, { item_id: "", cantidad: "", monto: "" }])}>+ Agregar línea</button>
        <p className="suave">Monto neto = lo que cuesta toda la línea, sin IVA. Total neto: <strong>{plata(total)}</strong></p>
        <label className="campo"><span>Nota (opcional)</span><input value={nota} onChange={(e) => setNota(e.target.value)} maxLength={500} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={ocupado || !proveedor.trim() || !completas}>Registrar factura</button>
      </form>
    </Dialogo>
  );
}

function DetalleCompra({ id, alCerrar, alCambiar }: { id: number; alCerrar: () => void; alCambiar: (mensaje: string) => void }) {
  const [c, setC] = useState<Compra | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { pedir<Compra>(`/compras/${id}`).then(setC).catch((e) => setError(e.message)); }, [id]);
  const anular = async () => {
    if (!confirm("¿Anular esta factura? Solo se puede si aún no se recibió.")) return;
    try { await pedir(`/compras/${id}/anular`, { metodo: "POST" }); alCambiar("Factura anulada."); } catch (e: any) { setError(e.message); }
  };
  return (
    <Dialogo titulo={c ? `${c.proveedor}${c.numero_documento ? ` · N° ${c.numero_documento}` : ""}` : "Factura"} alCerrar={alCerrar}>
      {error && <p className="error" role="alert">{error}</p>}
      {!c ? <p className="suave">Cargando…</p> : (
        <>
          <p><span className="chip">{ESTADO[c.estado] ?? c.estado}</span></p>
          {c.nota && <p className="suave">{c.nota}</p>}
          <div className="tabla-scroll">
            <table>
              <thead><tr><th>Ítem</th><th>Factura</th><th>Recibido</th><th>Diferencia</th></tr></thead>
              <tbody>
                {c.lineas.map((l) => (
                  <tr key={l.id} className={l.diferencia !== null && Number(l.diferencia) !== 0 ? "fila-alerta" : undefined}>
                    <td><strong>{l.item}</strong></td>
                    <td>{cant(l.cantidad_facturada)} {l.unidad_base}</td>
                    <td>{l.cantidad_recibida === null ? "—" : `${cant(l.cantidad_recibida)} ${l.unidad_base}`}</td>
                    <td>{l.diferencia === null ? "—" : Number(l.diferencia) === 0 ? "Sin diferencia" : `${Number(l.diferencia) > 0 ? "+" : ""}${cant(l.diferencia)} ${l.unidad_base}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {c.estado === "por_recibir" && <button className="secundario" onClick={anular}>Anular factura</button>}
        </>
      )}
    </Dialogo>
  );
}
