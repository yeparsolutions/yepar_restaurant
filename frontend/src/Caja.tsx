// ============================================================
// YEPAR RESTAURANT — frontend/src/Caja.tsx
// La pantalla del cajero: abre su turno, cobra las cuentas que piden los meseros, entrega propinas
// y al final cuenta el cajón.
// Analogía: el mostrador de la caja. El mesero trae la cuenta, el cajero cobra (efectivo, tarjeta o
// transferencia, total o por partes) y al terminar el turno cuenta el cajón: debe calzar con lo cobrado.
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { pedir, type Sesion } from "./api";
import { Marca } from "./App";
import { Dialogo, nuevoId, plata } from "./Mesero";

type Turno = { id: number; caja: string; fondo: string; abierto_en: string | null };
type CajaT = { id: number; nombre: string };
type Terminal = { id: number; nombre: string };
type Mesa = { mesa_id: number; nombre: string; estado: string; pedido_id: string | null };
type Cuenta = { subtotal: string; descuento: string; propina: string; total: string; pagado: string; pendiente: string };
type Linea = { id: string; nombre: string; cantidad: number; estado: string; total: string };
type Pedido = { id: string; mesa: string | null; estado: string; lineas: Linea[]; cuenta: Cuenta };
type Pago = { vuelto: string | null; pedido_estado: string; documento_estado: string | null; documento_folio: string | null; cuenta: Cuenta };
type Saldo = { mesero_id: number | null; nombre: string | null; monto: string };
type Arqueo = { fondo: string; efectivo_cobrado: string; esperado: string; cantidad_pagos: number };

const num = (v: string | number | null | undefined) => Number(v ?? 0);

export default function Caja({ sesion, alSalir }: { sesion: Sesion; alSalir: () => void }) {
  const [turno, setTurno] = useState<Turno | null | undefined>(undefined); // undefined = cargando
  const [error, setError] = useState("");
  const [cerrando, setCerrando] = useState(false);
  const [vista, setVista] = useState<"cobrar" | "propinas">("cobrar");
  const [pedidoId, setPedidoId] = useState<string | null>(null);

  const cargarTurno = useCallback(async () => {
    try {
      setTurno(await pedir<Turno>("/turnos/actual"));
    } catch (e: any) {
      // 404 = no hay turno abierto: es un estado normal, no un error.
      if (e.estado === 404) setTurno(null);
      else { setError(e.message); setTurno(null); }
    }
  }, []);
  useEffect(() => { cargarTurno(); }, [cargarTurno]);

  return (
    <>
      <header className="barra">
        <Marca />
        <span className="suave">Caja · {sesion.usuario.nombre}{turno ? ` · ${turno.caja}` : ""}</span>
        <span style={{ flex: 1 }} />
        {turno && <button className="secundario" onClick={() => setCerrando(true)}>Cerrar turno</button>}
        <button className="secundario" onClick={alSalir}>Salir</button>
      </header>
      <main className="contenido">
        {error && <p className="error" role="alert">{error}</p>}
        {turno === undefined ? <p className="suave">Cargando…</p> : turno === null ? (
          <AbrirTurno alAbrir={(t) => { setError(""); setTurno(t); }} />
        ) : pedidoId ? (
          <Cobro pedidoId={pedidoId} alVolver={() => setPedidoId(null)} />
        ) : (
          <>
            <nav className="pestanas" aria-label="Caja">
              <button className={`pestana ${vista === "cobrar" ? "activa" : ""}`} onClick={() => setVista("cobrar")}>Cobrar</button>
              <button className={`pestana ${vista === "propinas" ? "activa" : ""}`} onClick={() => setVista("propinas")}>Propinas</button>
            </nav>
            {vista === "cobrar" ? <PorCobrar alAbrir={setPedidoId} /> : <Propinas />}
          </>
        )}
      </main>
      {cerrando && turno && <CerrarTurno turno={turno} alCerrar={() => setCerrando(false)} alTerminar={() => { setCerrando(false); setTurno(null); }} />}
    </>
  );
}

// ── Abrir turno ─────────────────────────────────────────────
function AbrirTurno({ alAbrir }: { alAbrir: (t: Turno) => void }) {
  const [cajas, setCajas] = useState<CajaT[]>([]);
  const [cajaId, setCajaId] = useState("");
  const [fondo, setFondo] = useState("0");
  const [error, setError] = useState("");
  useEffect(() => {
    pedir<CajaT[]>("/cajas").then((c) => { setCajas(c); setCajaId(String(c[0]?.id ?? "")); }).catch((e) => setError(e.message));
  }, []);
  const abrir = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError("");
    try {
      alAbrir(await pedir<Turno>("/turnos", { json: { caja_id: Number(cajaId), fondo: fondo || "0" } }));
    } catch (e: any) {
      setError(e.message);
    }
  };
  return (
    <form className="formulario" onSubmit={abrir} style={{ maxWidth: 440 }}>
      <h1>Abrir turno</h1>
      <p className="suave">Cuenta el dinero de cambio que dejas en el cajón: será tu fondo inicial.</p>
      <label className="campo"><span>Caja</span>
        <select value={cajaId} onChange={(e) => setCajaId(e.target.value)} required>
          {cajas.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
        </select>
      </label>
      <label className="campo"><span>Fondo de cambio</span>
        <input type="number" inputMode="decimal" min="0" step="any" value={fondo} onChange={(e) => setFondo(e.target.value)} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <button type="submit" disabled={!cajaId}>Abrir turno</button>
    </form>
  );
}

// ── Cuentas por cobrar ──────────────────────────────────────
function PorCobrar({ alAbrir }: { alAbrir: (pedidoId: string) => void }) {
  const [mesas, setMesas] = useState<Mesa[] | null>(null);
  const [error, setError] = useState("");
  const [todas, setTodas] = useState(false);
  const cargar = useCallback(async () => {
    try { setMesas(await pedir<Mesa[]>("/mesas")); setError(""); } catch (e: any) { setError(e.message); }
  }, []);
  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 8000);
    return () => clearInterval(t);
  }, [cargar]);

  if (!mesas) return <p className="suave">{error || "Cargando…"}</p>;
  const conCuenta = mesas.filter((m) => m.pedido_id && (todas || m.estado === "cuenta_pedida"));
  return (
    <>
      <div className="encabezado">
        <h1>Cuentas por cobrar</h1>
        <label className="opcion" style={{ margin: 0 }}>
          <input type="checkbox" checked={todas} onChange={(e) => setTodas(e.target.checked)} />
          <span>Ver también mesas abiertas</span>
        </label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {conCuenta.length === 0 ? (
        <p className="suave">No hay cuentas pedidas. Cuando un mesero pida la cuenta, aparecerá aquí.</p>
      ) : (
        <div className="carta">
          {conCuenta.map((m) => (
            <button key={m.mesa_id} className={`plato ${m.estado === "cuenta_pedida" ? "falta" : ""}`} onClick={() => alAbrir(m.pedido_id!)}>
              <strong>{m.nombre}</strong>
              <small>{m.estado === "cuenta_pedida" ? "Pidió la cuenta" : "Abierta"}</small>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

// ── Cobrar una cuenta ───────────────────────────────────────
function Cobro({ pedidoId, alVolver }: { pedidoId: string; alVolver: () => void }) {
  const [pedido, setPedido] = useState<Pedido | null>(null);
  const [terminales, setTerminales] = useState<Terminal[]>([]);
  const [pctSugerido, setPctSugerido] = useState<number>(10);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [ultimo, setUltimo] = useState<Pago | null>(null);
  // formulario de pago
  const [medio, setMedio] = useState<"efectivo" | "tarjeta" | "transferencia">("efectivo");
  const [monto, setMonto] = useState("");
  const [recibido, setRecibido] = useState("");
  const [operacion, setOperacion] = useState("");
  const [terminalId, setTerminalId] = useState("");
  const [otraPropina, setOtraPropina] = useState("");
  const [descuento, setDescuento] = useState("");

  const recargar = useCallback(async () => {
    try {
      const p = await pedir<Pedido>(`/pedidos/${pedidoId}`);
      setPedido(p);
      setMonto((m) => (m === "" ? p.cuenta.pendiente : m));
    } catch (e: any) { setError(e.message); }
  }, [pedidoId]);
  useEffect(() => {
    recargar();
    pedir<Terminal[]>("/terminales").then((t) => { setTerminales(t); setTerminalId(String(t[0]?.id ?? "")); }).catch(() => {});
    pedir<{ propina_sugerida_pct: string | number }>("/configuracion/cobro").then((c) => setPctSugerido(num(c.propina_sugerida_pct))).catch(() => {});
  }, [recargar]);

  // Ejecuta una acción de la cuenta; al terminar vuelve a pedir la cuenta y deja el monto al pendiente.
  const hacer = async (fn: () => Promise<unknown>, ok = "") => {
    setOcupado(true); setError(""); setAviso("");
    try { await fn(); if (ok) setAviso(ok); setMonto(""); } catch (e: any) { setError(e.message); } finally { setOcupado(false); recargar(); }
  };
  const propina = (m: number | null) => hacer(() => pedir(`/pedidos/${pedidoId}/propina`, { json: m === null ? {} : { monto: String(m) } }), "Propina anotada.");
  const aplicarDescuento = () => hacer(() => pedir(`/pedidos/${pedidoId}/descuento`, { json: { porcentaje: descuento } }), "Descuento aplicado.");
  const cobrar = (ev: React.FormEvent) => {
    ev.preventDefault();
    hacer(async () => {
      const r = await pedir<Pago>(`/pedidos/${pedidoId}/pagos`, {
        json: {
          medio, monto, pago_id: nuevoId(),
          recibido: medio === "efectivo" && recibido ? recibido : null,
          numero_operacion: medio !== "efectivo" ? operacion.trim() : null,
          terminal_id: medio === "tarjeta" ? Number(terminalId) : null,
        },
      });
      setUltimo(r); setRecibido(""); setOperacion("");
    });
  };

  if (!pedido) return <p className="suave">{error || "Abriendo la cuenta…"}</p>;
  const c = pedido.cuenta;
  const cerrada = pedido.estado === "cerrado";
  const vuelto = medio === "efectivo" && recibido ? num(recibido) - num(monto) : null;

  return (
    <div className="pedido-grid">
      <section>
        <div className="encabezado">
          <h1>{pedido.mesa ?? "Cuenta"}</h1>
          <button className="secundario" onClick={alVolver}>← Cuentas</button>
        </div>
        <ul className="lineas">
          {pedido.lineas.filter((l) => l.estado !== "cancelada").map((l) => (
            <li key={l.id} className="linea"><div><strong>{l.cantidad}× {l.nombre}</strong></div><span>{plata(l.total)}</span></li>
          ))}
        </ul>
        <dl className="cuenta">
          <div><dt>Subtotal</dt><dd>{plata(c.subtotal)}</dd></div>
          {num(c.descuento) > 0 && <div><dt>Descuento</dt><dd>−{plata(c.descuento)}</dd></div>}
          <div><dt>Propina</dt><dd>{plata(c.propina)}</dd></div>
          <div className="total"><dt>Total</dt><dd>{plata(c.total)}</dd></div>
          <div><dt>Pagado</dt><dd>{plata(c.pagado)}</dd></div>
          <div className="total"><dt>Pendiente</dt><dd>{plata(c.pendiente)}</dd></div>
        </dl>
      </section>

      <section>
        {error && <p className="error" role="alert">{error}</p>}
        {aviso && !error && <p className="exito" role="status">{aviso}</p>}
        {cerrada ? (
          <div className="resultado ok" role="status">
            <h2 style={{ marginTop: 0 }}>Cuenta cerrada ✓</h2>
            {ultimo?.vuelto && num(ultimo.vuelto) > 0 && <p>Vuelto a entregar: <strong>{plata(ultimo.vuelto)}</strong></p>}
            {ultimo?.documento_estado && <p>Boleta/factura: {ultimo.documento_estado}{ultimo.documento_folio ? ` · folio ${ultimo.documento_folio}` : ""}</p>}
            <button onClick={alVolver}>Siguiente cuenta</button>
          </div>
        ) : (
          <>
            <h2 style={{ marginTop: 0 }}>Propina y descuento</h2>
            <div className="acciones">
              <button className="secundario" disabled={ocupado} onClick={() => propina(null)}>Sugerida ({pctSugerido}%)</button>
              <button className="secundario" disabled={ocupado} onClick={() => propina(0)}>Sin propina</button>
            </div>
            <div className="en-linea">
              <input type="number" inputMode="decimal" min="0" placeholder="Otra propina" aria-label="Otra propina" value={otraPropina} onChange={(e) => setOtraPropina(e.target.value)} />
              <button className="secundario" disabled={ocupado || !otraPropina} onClick={() => propina(num(otraPropina))}>Anotar</button>
            </div>
            <div className="en-linea">
              <input type="number" inputMode="decimal" min="0" max="100" placeholder="Descuento %" aria-label="Descuento en porcentaje" value={descuento} onChange={(e) => setDescuento(e.target.value)} />
              <button className="secundario" disabled={ocupado || !descuento} onClick={aplicarDescuento}>Aplicar</button>
            </div>

            <h2>Cobrar</h2>
            <form className="formulario" style={{ marginTop: 0 }} onSubmit={cobrar}>
              <div className="acciones" role="tablist">
                {(["efectivo", "tarjeta", "transferencia"] as const).map((m) => (
                  <button type="button" key={m} role="tab" aria-selected={medio === m} className={`pestana ${medio === m ? "activa" : ""}`} onClick={() => setMedio(m)}>
                    {m === "efectivo" ? "Efectivo" : m === "tarjeta" ? "Tarjeta" : "Transferencia"}
                  </button>
                ))}
              </div>
              <label className="campo"><span>Monto a cobrar</span>
                <input type="number" inputMode="decimal" min="0" step="any" value={monto} onChange={(e) => setMonto(e.target.value)} required />
                <small>Para dividir la cuenta, cobra una parte ahora y el resto después.</small>
              </label>
              {medio === "efectivo" && (
                <label className="campo"><span>Recibido</span>
                  <input type="number" inputMode="decimal" min="0" step="any" value={recibido} onChange={(e) => setRecibido(e.target.value)} />
                  {vuelto !== null && <small>{vuelto >= 0 ? `Vuelto: ${plata(vuelto)}` : `Faltan ${plata(-vuelto)}`}</small>}
                </label>
              )}
              {medio === "tarjeta" && (
                <label className="campo"><span>Terminal</span>
                  <select value={terminalId} onChange={(e) => setTerminalId(e.target.value)} required>
                    {terminales.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
                  </select>
                </label>
              )}
              {medio !== "efectivo" && (
                <label className="campo"><span>Número de operación</span>
                  <input value={operacion} onChange={(e) => setOperacion(e.target.value)} required maxLength={60} />
                </label>
              )}
              <button type="submit" disabled={ocupado || !monto}>Cobrar {monto ? plata(monto) : ""}</button>
            </form>
          </>
        )}
      </section>
    </div>
  );
}

// ── Propinas por entregar ───────────────────────────────────
function Propinas() {
  const [saldos, setSaldos] = useState<Saldo[] | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const cargar = useCallback(() => pedir<Saldo[]>("/propinas/saldos").then(setSaldos).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); }, [cargar]);
  const entregar = async (s: Saldo) => {
    setError(""); setAviso("");
    try {
      const r = await pedir<{ entregado: string }>("/propinas/entregar", { json: { mesero_id: s.mesero_id } });
      setAviso(`Entregaste ${plata(r.entregado)} a ${s.nombre}.`);
    } catch (e: any) { setError(e.message); }
    cargar();
  };
  return (
    <>
      <h1>Propinas por entregar</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {aviso && !error && <p className="exito" role="status">{aviso}</p>}
      {!saldos ? <p className="suave">Cargando…</p> : saldos.length === 0 ? <p className="suave">No hay propinas pendientes.</p> : (
        <ul className="lineas">
          {saldos.map((s) => (
            <li key={s.mesero_id ?? "grupal"} className="linea">
              <div><strong>{s.mesero_id === null ? "Fondo grupal (sin repartir)" : s.nombre ?? `Mesero ${s.mesero_id}`}</strong></div>
              <span>{plata(s.monto)}</span>
              {s.mesero_id !== null && <button onClick={() => entregar(s)}>Entregar</button>}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ── Cerrar turno: contar el cajón ───────────────────────────
function CerrarTurno({ turno, alCerrar, alTerminar }: { turno: Turno; alCerrar: () => void; alTerminar: () => void }) {
  const [arqueo, setArqueo] = useState<Arqueo | null>(null);
  const [contado, setContado] = useState("");
  const [nota, setNota] = useState("");
  const [error, setError] = useState("");
  const [fin, setFin] = useState<{ diferencia: string | null } | null>(null);
  useEffect(() => { pedir<Arqueo>(`/turnos/${turno.id}/arqueo`).then(setArqueo).catch((e) => setError(e.message)); }, [turno.id]);

  const diferencia = contado !== "" && arqueo ? num(contado) - num(arqueo.esperado) : 0;
  const cerrar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError("");
    try {
      const t = await pedir<{ diferencia: string | null }>(`/turnos/${turno.id}/cerrar`, { json: { contado, nota: nota.trim() || null } });
      setFin(t);
    } catch (e: any) { setError(e.message); }
  };

  if (fin) {
    const d = num(fin.diferencia);
    return (
      <Dialogo titulo="Turno cerrado" alCerrar={alTerminar}>
        <p className={d === 0 ? "exito" : "error"} role="status">{d === 0 ? "El cajón calza exacto. ¡Buen turno!" : `Diferencia de ${plata(d)}. Quedó registrada para el administrador.`}</p>
        <button onClick={alTerminar}>Listo</button>
      </Dialogo>
    );
  }
  return (
    <Dialogo titulo="Cerrar turno" alCerrar={alCerrar}>
      {arqueo && (
        <dl className="cuenta">
          <div><dt>Fondo inicial</dt><dd>{plata(arqueo.fondo)}</dd></div>
          <div><dt>Efectivo cobrado ({arqueo.cantidad_pagos} pagos)</dt><dd>{plata(arqueo.efectivo_cobrado)}</dd></div>
          <div className="total"><dt>Debería haber</dt><dd>{plata(arqueo.esperado)}</dd></div>
        </dl>
      )}
      <form onSubmit={cerrar} style={{ display: "grid", gap: 8 }}>
        <label className="campo"><span>Cuenta el cajón: ¿cuánto hay?</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={contado} onChange={(e) => setContado(e.target.value)} required />
          {contado !== "" && <small>{diferencia === 0 ? "Calza exacto." : diferencia > 0 ? `Sobran ${plata(diferencia)}.` : `Faltan ${plata(-diferencia)}.`}</small>}
        </label>
        {diferencia !== 0 && (
          <label className="campo"><span>Nota (obligatoria si hay diferencia)</span>
            <input value={nota} onChange={(e) => setNota(e.target.value)} maxLength={300} required />
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={contado === ""}>Cerrar turno</button>
      </form>
    </Dialogo>
  );
}
