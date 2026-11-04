// ============================================================
// YEPAR RESTAURANT — frontend/src/Resumen.tsx
// El dashboard: cómo va el día de un vistazo. Se actualiza solo cada 30 segundos.
//   · Ventas de hoy (cuentas cerradas, descuentos, propinas, medios de pago)
//   · Mesas: cuántas libres, ocupadas, con comida lista o esperando cobrar
//   · Stock bajo: qué comprar
//   · Rentabilidad de la carta: costo y margen de cada plato
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { pedir, type Sesion } from "./api";

type Sucursal = { id: number; nombre: string };
type Resumen = { cerradas: number; ventas: string; descuentos: string; propinas: string; total_cobrado: string; por_medio: Record<string, string>; turnos_con_diferencia: { turno_id: number; diferencia: string }[] };
type Mesa = { mesa_id: number; estado: "libre" | "ocupada" | "lista" | "cuenta_pedida" };
type Alerta = { item_id: number; nombre: string; disponible: string; stock_minimo: string; se_produce: boolean; unidad: string };
type Compras = { lineas: unknown[]; costo_total_estimado: string };
type Item = { id: number; nombre: string; tipo: string; precio_venta: string | null; tiene_receta: boolean };
type Costo = { item_id: number; nombre: string; costo_unitario: string; precio_venta: string | null; margen_pct: string | null };

const plata = (v: string | number) => "$" + Math.round(Number(v)).toLocaleString("es-CL");
const num = (v: string) => Number(v).toLocaleString("es-CL", { maximumFractionDigits: 2 });
const MEDIOS: Record<string, string> = { efectivo: "Efectivo", tarjeta: "Tarjeta", transferencia: "Transferencia" };

export default function ResumenDia({ sesion }: { sesion: Sesion }) {
  const [locales, setLocales] = useState<Sucursal[]>([]);
  const [local, setLocal] = useState<number | null>(sesion.usuario.sucursal_id);
  const [error, setError] = useState("");

  useEffect(() => {
    pedir<Sucursal[]>("/sucursales")
      .then((l) => { setLocales(l); setLocal((a) => a ?? l[0]?.id ?? null); })
      .catch((e) => setError(e.message));
  }, []);

  return (
    <section>
      <div className="encabezado">
        <h1>Resumen de hoy</h1>
        {locales.length > 1 && (
          <select value={local ?? ""} onChange={(e) => setLocal(Number(e.target.value))} aria-label="Local" style={{ maxWidth: 260 }}>
            {locales.map((l) => <option key={l.id} value={l.id}>{l.nombre}</option>)}
          </select>
        )}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {local !== null && <Tablero key={local} local={local} />}
    </section>
  );
}

function Tablero({ local }: { local: number }) {
  // Cada tarjeta carga por separado: si una falla (undefined = aún no llega, null = falló), las demás se siguen viendo.
  const [res, setRes] = useState<Resumen | null | undefined>(undefined);
  const [mesas, setMesas] = useState<Mesa[] | null | undefined>(undefined);
  const [alertas, setAlertas] = useState<Alerta[] | null | undefined>(undefined);
  const [compras, setCompras] = useState<Compras | null>(null);
  const [costos, setCostos] = useState<Costo[] | null | undefined>(undefined);

  const cargar = useCallback(async () => {
    const inicio = new Date();
    inicio.setHours(0, 0, 0, 0); // el día empieza a medianoche, en la hora del restaurante
    const hasta = new Date(Date.now() + 60_000);
    const q = `sucursal_id=${local}`;
    const o = <T,>(p: Promise<T>) => p.catch(() => null);
    o(pedir<Resumen>(`/cierre/resumen?${q}&desde=${encodeURIComponent(inicio.toISOString())}&hasta=${encodeURIComponent(hasta.toISOString())}`)).then(setRes);
    o(pedir<Mesa[]>(`/mesas?${q}`)).then(setMesas);
    o(pedir<Alerta[]>(`/inventario/alertas?${q}`)).then(setAlertas);
    o(pedir<Compras>(`/inventario/lista-compras?${q}`)).then(setCompras);
    o(pedir<Item[]>("/items?tipo=vendible_preparado")).then(async (items) => {
      if (!items) return setCostos(null);
      const conReceta = items.filter((i) => i.tiene_receta).slice(0, 40);
      setCostos((await Promise.all(conReceta.map((i) => o(pedir<Costo>(`/items/${i.id}/costo`))))).filter((c): c is Costo => c !== null));
    });
  }, [local]);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 30_000);
    return () => clearInterval(t);
  }, [cargar]);

  const cuenta = (e: Mesa["estado"]) => (mesas ?? []).filter((m) => m.estado === e).length;
  const aviso = (x: unknown) => (x === undefined ? <p className="suave">Cargando…</p> : <p className="error">No se pudo cargar esta parte. Se reintenta sola.</p>);
  return (
    <>
      <div className="kpis">
        <Kpi etiqueta="Ventas de hoy" valor={res ? plata(res.ventas) : "…"} nota={!res ? "" : res.cerradas === 0 ? "Aún sin cuentas cerradas" : `${res.cerradas} cuenta(s) cerrada(s)`} />
        <Kpi etiqueta="Propinas" valor={res ? plata(res.propinas) : "…"} nota="Del día" />
        <Kpi etiqueta="Descuentos" valor={res ? plata(res.descuentos) : "…"} nota="Del día" />
        <Kpi etiqueta="Total cobrado" valor={res ? plata(res.total_cobrado) : "…"} nota="Ventas + propinas" />
      </div>

      {res && res.turnos_con_diferencia.length > 0 && (
        <p className="error" role="alert">
          {res.turnos_con_diferencia.length} turno(s) de caja no cuadraron. Revísalos antes de cerrar el día.
        </p>
      )}

      <div className="tablero">
        <div className="panelito">
          <h2>Salón</h2>
          {!mesas ? aviso(mesas) : mesas.length === 0 ? <p className="suave">Aún no hay mesas. Créalas en Configuración.</p> : (
            <ul className="estados">
              <li className="e-libre"><b>{cuenta("libre")}</b> libres</li>
              <li className="e-ocupada"><b>{cuenta("ocupada")}</b> ocupadas</li>
              <li className="e-lista"><b>{cuenta("lista")}</b> con comida lista</li>
              <li className="e-cuenta"><b>{cuenta("cuenta_pedida")}</b> piden la cuenta</li>
            </ul>
          )}
          {mesas && <p className="suave">{mesas.length} mesa(s) en total.</p>}
        </div>

        <div className="panelito">
          <h2>Cobros por medio</h2>
          {!res ? aviso(res) : Object.keys(res.por_medio).length === 0 ? <p className="suave">Sin cobros todavía.</p> : (
            <ul className="lista">
              {Object.entries(res.por_medio).map(([k, v]) => (
                <li key={k} className="par"><span>{MEDIOS[k] ?? k}</span><strong>{plata(v)}</strong></li>
              ))}
            </ul>
          )}
        </div>

        <div className="panelito">
          <h2>Stock bajo</h2>
          {!alertas ? aviso(alertas) : alertas.length === 0 ? <p className="suave">Todo en orden: nada bajo su mínimo.</p> : (
            <>
              <ul className="lista">
                {alertas.slice(0, 6).map((a) => (
                  <li key={a.item_id} className="par">
                    <span>{a.nombre}{a.se_produce && " (se produce)"}</span>
                    <span className="alerta">{num(a.disponible)} {a.unidad} / mín. {num(a.stock_minimo)} {a.unidad}</span>
                  </li>
                ))}
              </ul>
              {alertas.length > 6 && <p className="suave">y {alertas.length - 6} más.</p>}
              {compras && <p className="suave">Reponerlo costaría cerca de <strong>{plata(compras.costo_total_estimado)}</strong>.</p>}
            </>
          )}
        </div>
      </div>

      <div className="panelito ancho">
        <h2>Rentabilidad de la carta</h2>
        {!costos ? aviso(costos) : costos.length === 0 ? <p className="suave">Carga platos con receta para ver su costo y margen.</p> : (
          <table>
            <thead><tr><th>Plato</th><th>Precio</th><th>Costo</th><th>Margen</th></tr></thead>
            <tbody>
              {[...costos].sort((a, b) => Number(a.margen_pct ?? 0) - Number(b.margen_pct ?? 0)).map((c) => {
                const m = c.margen_pct === null ? null : Number(c.margen_pct);
                return (
                  <tr key={c.item_id}>
                    <td>{c.nombre}</td>
                    <td>{c.precio_venta ? plata(c.precio_venta) : "—"}</td>
                    <td>{plata(c.costo_unitario)}</td>
                    <td>
                      {m === null ? "—" : (
                        <span className="margen" title={`${m.toFixed(1)} %`}>
                          <span className={"barra-margen " + (m < 50 ? "bajo" : m < 65 ? "medio" : "alto")} style={{ width: `${Math.max(4, Math.min(100, m))}%` }} />
                          <b>{m.toFixed(1)} %</b>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="suave">Ordenado del margen más bajo al más alto: lo de arriba es lo que conviene revisar primero.</p>
      </div>
    </>
  );
}

function Kpi({ etiqueta, valor, nota }: { etiqueta: string; valor: string; nota: string }) {
  return (
    <div className="kpi">
      <span>{etiqueta}</span>
      <strong>{valor}</strong>
      <small>{nota}</small>
    </div>
  );
}
