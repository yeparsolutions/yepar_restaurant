// ============================================================
// YEPAR RESTAURANT — frontend/src/Despacho.tsx
// Delivery con Yepar Go: pedir el motorista de una cuenta para llevar y seguir sus entregas.
// Analogía: el mostrador de despacho. La cuenta sale lista de la cocina; aquí se anota a quién y adónde va,
// y Yepar Go manda a un motorista. El cliente recibe un link para ver por dónde viene su pedido.
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { ErrorApi, pedir } from "./api";
import { Dialogo } from "./Mesero";

export type DespachoT = {
  id: number; pedido_id: string; estado: string; destinatario: string; direccion: string; telefono: string | null;
  go_numero: string | null; estado_go: string | null; seguimiento_url: string | null; intentos: number; ultimo_error: string | null;
};

const ESTADO_GO: Record<string, string> = {
  pending: "Esperando motorista", assigned: "Motorista asignado", in_route: "En camino", delivered: "Entregado",
  failed: "Falló la entrega", cancelled: "Cancelado", returned: "Devuelto",
};
/** Texto claro del estado de un reparto, sea de nuestro lado o ya en manos de Yepar Go. */
export function textoDespacho(d: Pick<DespachoT, "estado" | "estado_go">): string {
  if (d.estado === "pendiente") return "Pendiente de confirmar con Yepar Go";
  if (d.estado === "rechazado") return "Yepar Go lo rechazó";
  return d.estado_go ? (ESTADO_GO[d.estado_go] ?? d.estado_go) : "Pedido a Yepar Go";
}

/** Estado del reparto de una cuenta + botón para pedirlo (o corregirlo si falló). */
export function PanelDespacho({ pedidoId, puedePedir = true }: { pedidoId: string; puedePedir?: boolean }) {
  const [d, setD] = useState<DespachoT | null | undefined>(undefined);   // undefined = cargando, null = sin reparto
  const [abierto, setAbierto] = useState(false);
  const [aviso, setAviso] = useState("");
  const cargar = useCallback(async () => {
    try { setD(await pedir<DespachoT>(`/pedidos/${pedidoId}/despacho`)); }
    catch (e) { if (e instanceof ErrorApi && (e.estado === 404 || e.estado === 0)) setD((x) => (x === undefined ? null : x)); else setD(null); }
  }, [pedidoId]);
  useEffect(() => { cargar(); const t = setInterval(cargar, 15000); return () => clearInterval(t); }, [cargar]);
  if (d === undefined) return null;
  const rehacer = !d || d.estado !== "creado";
  return (
    <div className="formulario" style={{ marginTop: 12 }}>
      <h3 style={{ marginBottom: 4 }}>Reparto a domicilio</h3>
      {aviso && <p className="exito" role="status">{aviso}</p>}
      {d ? (
        <>
          <p><span className="chip">{textoDespacho(d)}</span> {d.go_numero && <strong>{d.go_numero}</strong>}</p>
          <p className="suave">{d.destinatario} · {d.direccion}{d.telefono ? ` · ${d.telefono}` : ""}</p>
          {d.ultimo_error && d.estado !== "creado" && <p className="error">{d.ultimo_error}</p>}
          {d.seguimiento_url && <p><a href={d.seguimiento_url} target="_blank" rel="noreferrer">Link de seguimiento para el cliente</a></p>}
        </>
      ) : <p className="suave">Esta cuenta aún no tiene motorista.</p>}
      {puedePedir && rehacer && (
        <button className="secundario" onClick={() => { setAviso(""); setAbierto(true); }}>{d ? "Corregir y reintentar" : "Pedir reparto con Yepar Go"}</button>
      )}
      {abierto && <DialogoReparto pedidoId={pedidoId} previo={d ?? null} alCerrar={() => setAbierto(false)} alTerminar={(m) => { setAbierto(false); setAviso(m); cargar(); }} />}
    </div>
  );
}

function DialogoReparto({ pedidoId, previo, alCerrar, alTerminar }: {
  pedidoId: string; previo: DespachoT | null; alCerrar: () => void; alTerminar: (mensaje: string) => void;
}) {
  const [destinatario, setDestinatario] = useState(previo?.destinatario ?? "");
  const [direccion, setDireccion] = useState(previo?.direccion ?? "");
  const [telefono, setTelefono] = useState(previo?.telefono ?? "");
  const [ciudad, setCiudad] = useState("");
  const [notas, setNotas] = useState("");
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError(""); setOcupado(true);
    try {
      const r = await pedir<DespachoT>(`/pedidos/${pedidoId}/despacho`, {
        json: { destinatario: destinatario.trim(), direccion: direccion.trim(), telefono: telefono.trim() || null, ciudad: ciudad.trim() || null, notas: notas.trim() || null },
      });
      alTerminar(r.estado === "pendiente" ? "Yepar Go no respondió: el reparto quedó pendiente y se reintentará." : `Motorista pedido${r.go_numero ? ` (${r.go_numero})` : ""}.`);
    } catch (e: any) { setError(e.message); } finally { setOcupado(false); }
  };

  return (
    <Dialogo titulo="Pedir reparto con Yepar Go" alCerrar={alCerrar}>
      <form onSubmit={enviar} style={{ display: "grid", gap: 8 }}>
        <label className="campo"><span>Nombre del cliente</span><input value={destinatario} onChange={(e) => setDestinatario(e.target.value)} required minLength={2} maxLength={150} autoFocus /></label>
        <label className="campo"><span>Dirección de entrega</span><input value={direccion} onChange={(e) => setDireccion(e.target.value)} required minLength={3} maxLength={300} placeholder="Calle y número, depto." /></label>
        <label className="campo"><span>Comuna o ciudad (opcional)</span><input value={ciudad} onChange={(e) => setCiudad(e.target.value)} maxLength={100} /></label>
        <label className="campo"><span>Teléfono (opcional)</span><input type="tel" inputMode="tel" value={telefono} onChange={(e) => setTelefono(e.target.value)} maxLength={40} /></label>
        <label className="campo"><span>Indicaciones (opcional)</span><input value={notas} onChange={(e) => setNotas(e.target.value)} maxLength={300} placeholder="Ej.: tocar el timbre 2" /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={ocupado || destinatario.trim().length < 2 || direccion.trim().length < 3}>{ocupado ? "Pidiendo motorista…" : "Pedir motorista"}</button>
      </form>
    </Dialogo>
  );
}

/** Entregas en curso (caja): estado vivo de cada reparto, con botón para consultar a Yepar Go. */
export function Entregas() {
  const [lista, setLista] = useState<DespachoT[] | null>(null);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const cargar = useCallback(() => pedir<DespachoT[]>("/despachos?en_curso=true").then((l) => { setLista(l); setError(""); }).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 20000); return () => clearInterval(t); }, [cargar]);
  const accion = async (ruta: string) => {
    setOcupado(true); setError("");
    try { await pedir(ruta, { metodo: "POST" }); } catch (e: any) { setError(e.message); }
    setOcupado(false); cargar();
  };
  const hayPendientes = (lista ?? []).some((d) => d.estado === "pendiente");
  return (
    <>
      <div className="encabezado">
        <h1>Entregas en curso</h1>
        <div className="acciones">
          {hayPendientes && <button className="secundario" disabled={ocupado} onClick={() => accion("/despachos/reintentar")}>Reintentar pendientes</button>}
          <button className="secundario" disabled={ocupado} onClick={() => accion("/despachos/actualizar")}>Actualizar estado</button>
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!lista ? <p className="suave">Cargando…</p> : lista.length === 0 ? <p className="suave">No hay repartos en la calle.</p> : (
        <ul className="lineas">
          {lista.map((d) => (
            <li key={d.id} className="linea">
              <div>
                <strong>{d.destinatario}</strong>{d.go_numero ? ` · ${d.go_numero}` : ""}
                <div className="suave">{d.direccion}</div>
                {d.seguimiento_url && <a href={d.seguimiento_url} target="_blank" rel="noreferrer">Seguimiento</a>}
              </div>
              <span className="chip">{textoDespacho(d)}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
