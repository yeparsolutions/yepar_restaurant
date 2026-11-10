// ============================================================
// YEPAR RESTAURANT — frontend/src/Recepcion.tsx
// Recepción a ciegas de mercadería (cocinero): ve qué debe llegar, pero NO cuánto dice la factura.
// Analogía: contar la caja sin mirar el ticket. Quien recibe cuenta lo que realmente hay en la puerta;
// el administrador después compara con la factura. Así nadie "cuadra" el conteo por costumbre.
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { pedir } from "./api";
import { Dialogo } from "./Mesero";

type Pendiente = { id: number; proveedor: string; lineas: number };
type Presentacion = { id: number; nombre: string };
type LineaCiega = { linea_id: number | null; item_id: number; item: string; unidad_base: string; presentaciones: Presentacion[] };
type Hoja = { id: number; proveedor: string; lineas: LineaCiega[] };
type Conteo = { cantidad: string; unidad: string };   // unidad: "" = base, o el id de la presentación

/** Botón + diálogo de recepción para la pantalla de cocina. Se ve siempre; sin pedidos por recibir lo explica. */
export function BotonRecepcion() {
  const [pendientes, setPendientes] = useState<Pendiente[]>([]);
  const [abierto, setAbierto] = useState(false);
  const [aviso, setAviso] = useState("");
  const cargar = useCallback(() => pedir<Pendiente[]>("/compras/por-recibir").then(setPendientes).catch(() => {}), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 30000); return () => clearInterval(t); }, [cargar]);
  return (
    <>
      <button className="secundario" onClick={() => { setAviso(""); setAbierto(true); }}>Recibir mercadería{pendientes.length > 0 ? ` (${pendientes.length})` : ""}</button>
      {aviso && <span className="exito" role="status" style={{ padding: "4px 10px", borderRadius: 8 }}>{aviso}</span>}
      {abierto && <Recepcion pendientes={pendientes} alCerrar={() => setAbierto(false)} alTerminar={(m) => { setAbierto(false); setAviso(m); cargar(); }} />}
    </>
  );
}

function Recepcion({ pendientes, alCerrar, alTerminar }: { pendientes: Pendiente[]; alCerrar: () => void; alTerminar: (mensaje: string) => void }) {
  const [hoja, setHoja] = useState<Hoja | null>(null);
  const [conteos, setConteos] = useState<Record<number, Conteo>>({});
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const abrir = async (id: number) => {
    setError("");
    try { setHoja(await pedir<Hoja>(`/compras/${id}/recepcion`)); setConteos({}); } catch (e: any) { setError(e.message); }
  };
  const poner = (id: number, parcial: Partial<Conteo>) => setConteos((c) => ({ ...c, [id]: { ...{ cantidad: "", unidad: "" }, ...c[id], ...parcial } }));
  // Todas las líneas se cuentan: si no llegó, se escribe 0.
  const completa = !!hoja && hoja.lineas.every((l) => l.linea_id !== null && conteos[l.linea_id]?.cantidad !== undefined && conteos[l.linea_id]?.cantidad !== "");

  const enviar = async () => {
    if (!hoja) return;
    setError(""); setOcupado(true);
    try {
      await pedir(`/compras/${hoja.id}/recibir`, {
        json: {
          lineas: hoja.lineas.map((l) => {
            const c = conteos[l.linea_id!];
            return { linea_id: l.linea_id, cantidad: c.cantidad, ...(c.unidad ? { presentacion_id: Number(c.unidad) } : { unidad: l.unidad_base }) };
          }),
        },
      });
      alTerminar(`Recepción de ${hoja.proveedor} registrada: el stock ya subió.`);
    } catch (e: any) { setError(e.message); } finally { setOcupado(false); }
  };

  return (
    <Dialogo titulo={hoja ? `Recibir de ${hoja.proveedor}` : "Mercadería por recibir"} alCerrar={alCerrar}>
      {error && <p className="error" role="alert">{error}</p>}
      {!hoja && pendientes.length === 0 ? (
        <p className="suave">No hay mercadería por recibir. Cuando el administrador registre una compra, aparecerá aquí para que cuentes lo que llegó.</p>
      ) : !hoja ? (
        <ul className="lineas">
          {pendientes.map((p) => (
            <li key={p.id} className="linea">
              <div><strong>{p.proveedor}</strong><div className="suave">{p.lineas} producto{p.lineas === 1 ? "" : "s"}</div></div>
              <button onClick={() => abrir(p.id)}>Contar</button>
            </li>
          ))}
        </ul>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          <p className="suave">Cuenta lo que realmente llegó. Si algo no llegó, escribe 0.</p>
          {hoja.lineas.map((l) => (
            <div key={l.linea_id} className="linea-factura">
              <strong>{l.item}</strong>
              <input type="number" inputMode="decimal" min="0" step="any" aria-label={`Cantidad recibida de ${l.item}`} placeholder="Cantidad"
                value={conteos[l.linea_id!]?.cantidad ?? ""} onChange={(e) => poner(l.linea_id!, { cantidad: e.target.value })} />
              <select aria-label={`Unidad de ${l.item}`} value={conteos[l.linea_id!]?.unidad ?? ""} onChange={(e) => poner(l.linea_id!, { unidad: e.target.value })}>
                <option value="">{l.unidad_base}</option>
                {l.presentaciones.map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
              </select>
            </div>
          ))}
          <button disabled={!completa || ocupado} onClick={enviar}>Confirmar lo recibido</button>
        </div>
      )}
    </Dialogo>
  );
}
