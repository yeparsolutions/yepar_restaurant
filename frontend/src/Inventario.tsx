// ============================================================
// YEPAR RESTAURANT — frontend/src/Inventario.tsx
// El inventario del administrador: qué hay, qué falta, ingresar compras y anotar mermas.
// Analogía: la bodega con su libreta. Cada vez que llega mercadería se anota la entrada (y su costo);
// cada vez que algo se pierde, se anota la merma. Así lo que dice la libreta calza con lo que hay en el estante.
// ============================================================
import { useCallback, useEffect, useMemo, useState } from "react";
import { pedir } from "./api";
import { plata } from "./dinero";
import { Dialogo } from "./Mesero";

type Fila = { item_id: number; nombre: string; tipo: string; unidad: string; fisico: string; reservado: string; disponible: string; stock_minimo: string };
type LineaCompra = { item_id: number; nombre: string; cantidad_base: string; unidad: string; presentacion: string | null; cantidad_presentacion: number | null; costo_estimado?: string };
type ListaCompras = { lineas: LineaCompra[]; costo_total_estimado: string };

const MOTIVOS: [string, string][] = [["vencido", "Vencido"], ["danado", "Dañado"], ["error_preparacion", "Error de preparación"], ["sobrante", "Sobrante"], ["derrame", "Derrame"]];
const TIPOS: Record<string, string> = { materia_prima: "Materia prima", componente: "Preparación", vendible_reventa: "Reventa", vendible_preparado: "Plato" };

/** Cantidad sin ceros de más: 1000.000 → 1000, 2.500 → 2,5. */
const cant = (v: string | number) => Number(v).toLocaleString("es", { maximumFractionDigits: 3 });

export default function Inventario() {
  const [filas, setFilas] = useState<Fila[] | null>(null);
  const [lista, setLista] = useState<ListaCompras | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [buscar, setBuscar] = useState("");
  const [soloBajo, setSoloBajo] = useState(false);
  const [accion, setAccion] = useState<{ tipo: "compra" | "merma"; fila: Fila } | null>(null);

  const cargar = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([pedir<Fila[]>("/inventario/stock"), pedir<ListaCompras>("/inventario/lista-compras")]);
      setFilas(s); setLista(l); setError("");
    } catch (e: any) { setError(e.message); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);

  const visibles = useMemo(() => (filas ?? []).filter((f) =>
    (!soloBajo || num(f.disponible) < num(f.stock_minimo)) && f.nombre.toLowerCase().includes(buscar.trim().toLowerCase())), [filas, buscar, soloBajo]);
  const bajos = (filas ?? []).filter((f) => num(f.stock_minimo) > 0 && num(f.disponible) < num(f.stock_minimo)).length;

  return (
    <>
      <div className="encabezado">
        <h1>Inventario</h1>
        <span className="suave">{filas ? `${filas.length} ítems · ${bajos} bajo su mínimo` : ""}</span>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="exito" role="status">{aviso}</p>}

      <div className="en-linea">
        <input placeholder="Buscar ítem…" aria-label="Buscar ítem" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
        <label className="opcion" style={{ margin: 0 }}>
          <input type="checkbox" checked={soloBajo} onChange={(e) => setSoloBajo(e.target.checked)} /><span>Solo bajo mínimo</span>
        </label>
      </div>

      {!filas ? <p className="suave">Cargando…</p> : visibles.length === 0 ? <p className="suave">No hay ítems que mostrar.</p> : (
        <table>
          <thead><tr><th>Ítem</th><th>Tipo</th><th>Hay</th><th>Reservado</th><th>Disponible</th><th>Mínimo</th><th /></tr></thead>
          <tbody>
            {visibles.map((f) => {
              const bajo = num(f.stock_minimo) > 0 && num(f.disponible) < num(f.stock_minimo);
              return (
                <tr key={f.item_id} className={bajo ? "fila-alerta" : undefined}>
                  <td><strong>{f.nombre}</strong>{bajo && <span className="etiqueta-alerta"> bajo mínimo</span>}</td>
                  <td>{TIPOS[f.tipo] ?? f.tipo}</td>
                  <td>{cant(f.fisico)} {f.unidad}</td>
                  <td>{cant(f.reservado)}</td>
                  <td>{cant(f.disponible)} {f.unidad}</td>
                  <td>{num(f.stock_minimo) > 0 ? `${cant(f.stock_minimo)} ${f.unidad}` : "—"}</td>
                  <td className="acciones">
                    <button className="secundario" onClick={() => { setAviso(""); setAccion({ tipo: "compra", fila: f }); }}>Ingresar</button>
                    <button className="secundario" onClick={() => { setAviso(""); setAccion({ tipo: "merma", fila: f }); }}>Merma</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <h2>Qué comprar</h2>
      {!lista ? <p className="suave">Cargando…</p> : lista.lineas.length === 0 ? <p className="suave">Nada bajo su mínimo: no hace falta comprar.</p> : (
        <>
          <p className="suave">Cada ingrediente bajo su mínimo se repone hasta el doble de ese mínimo.</p>
          <ul className="lista">
            {lista.lineas.map((l) => (
              <li key={l.item_id} className="par">
                <span>{l.nombre}</span>
                <strong>{l.cantidad_presentacion && l.presentacion ? `${l.cantidad_presentacion} × ${l.presentacion}` : `${cant(l.cantidad_base)} ${l.unidad}`}</strong>
              </li>
            ))}
          </ul>
          <p>Costo estimado: <strong>{plata(lista.costo_total_estimado)}</strong></p>
        </>
      )}

      {accion && (
        <DialogoMovimiento accion={accion} alCerrar={() => setAccion(null)}
          alTerminar={(msg) => { setAccion(null); setAviso(msg); cargar(); }} />
      )}
    </>
  );
}

const num = (v: string | number | null | undefined) => Number(v ?? 0);

function DialogoMovimiento({ accion, alCerrar, alTerminar }: {
  accion: { tipo: "compra" | "merma"; fila: Fila }; alCerrar: () => void; alTerminar: (mensaje: string) => void;
}) {
  const { tipo, fila } = accion;
  const [cantidad, setCantidad] = useState("");
  const [costo, setCosto] = useState("");
  const [motivo, setMotivo] = useState("vencido");
  const [nota, setNota] = useState("");
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError(""); setOcupado(true);
    try {
      if (tipo === "compra") {
        const r = await pedir<{ stock_nuevo: string }>("/inventario/compras", {
          json: { item_id: fila.item_id, cantidad, unidad: fila.unidad, monto_neto: costo, nota: nota.trim() || null },
        });
        alTerminar(`Ingresaste ${cant(cantidad)} ${fila.unidad} de ${fila.nombre}. Ahora hay ${cant(r.stock_nuevo)} ${fila.unidad}.`);
      } else {
        const r = await pedir<{ stock_nuevo: string }>("/inventario/mermas", {
          json: { item_id: fila.item_id, cantidad, motivo, nota: nota.trim() || null },
        });
        alTerminar(`Merma anotada: ${cant(cantidad)} ${fila.unidad} de ${fila.nombre}. Quedan ${cant(r.stock_nuevo)} ${fila.unidad}.`);
      }
    } catch (e: any) { setError(e.message); } finally { setOcupado(false); }
  };

  return (
    <Dialogo titulo={tipo === "compra" ? `Ingresar compra · ${fila.nombre}` : `Anotar merma · ${fila.nombre}`} alCerrar={alCerrar}>
      <form onSubmit={enviar} style={{ display: "grid", gap: 8 }}>
        <label className="campo"><span>Cantidad ({fila.unidad})</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={cantidad} onChange={(e) => setCantidad(e.target.value)} required autoFocus />
          <small>Ahora hay {cant(fila.fisico)} {fila.unidad}.</small>
        </label>
        {tipo === "compra" ? (
          <label className="campo"><span>Costo total de esta compra (sin IVA)</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={costo} onChange={(e) => setCosto(e.target.value)} required />
            <small>Con esto el sistema calcula el costo promedio y el costo de tus platos.</small>
          </label>
        ) : (
          <label className="campo"><span>Motivo</span>
            <select value={motivo} onChange={(e) => setMotivo(e.target.value)}>{MOTIVOS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
          </label>
        )}
        <label className="campo"><span>Nota (opcional)</span>
          <input value={nota} onChange={(e) => setNota(e.target.value)} maxLength={255} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={ocupado || !cantidad || (tipo === "compra" && !costo)}>{tipo === "compra" ? "Ingresar" : "Anotar merma"}</button>
      </form>
    </Dialogo>
  );
}
