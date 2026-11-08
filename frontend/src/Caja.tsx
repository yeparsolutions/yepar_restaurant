// ============================================================
// YEPAR RESTAURANT — frontend/src/Caja.tsx
// La pantalla del cajero: abre su turno, cobra las cuentas que piden los meseros, entrega propinas
// y al final cuenta el cajón.
// Analogía: el mostrador de la caja. El mesero trae la cuenta, el cajero cobra (efectivo, tarjeta o
// transferencia, total o por partes) y al terminar el turno cuenta el cajón: debe calzar con lo cobrado.
// ============================================================
import { useCallback, useEffect, useState } from "react";
import { ErrorApi, pedir, type Sesion } from "./api";
import { Marca } from "./App";
import { Dialogo, nuevoId, plata } from "./Mesero";
import { guardarCache, leerCache } from "./sinConexion";
import {
  anotarPago, descartarRechazados, colaActual, enviarPagos, fijarCajero, iniciarPagos, pendienteDeEnvio, usePagosSinConexion,
} from "./pagosSinConexion";

type Turno = { id: number; caja: string; fondo: string; abierto_en: string | null };
type CajaT = { id: number; nombre: string };
type Terminal = { id: number; nombre: string };
type Mesa = { mesa_id: number; nombre: string; estado: string; pedido_id: string | null };
type Cuenta = { subtotal: string; descuento: string; propina: string; total: string; pagado: string; pendiente: string };
type Linea = { id: string; nombre: string; cantidad: number; estado: string; total: string };
type Pedido = { id: string; mesa: string | null; estado: string; lineas: Linea[]; cuenta: Cuenta };
type Pago = { vuelto: string | null; pedido_estado: string; documento_estado: string | null; documento_folio: string | null; cuenta: Cuenta };
type Supervisor = { id: number; nombre: string };
type Saldo = { mesero_id: number | null; nombre: string | null; monto: string };
type Cobrada = { pedido_id: string; mesa: string | null; cerrado_en: string | null; total: string; pagado: Record<string, string>; devuelto: Record<string, string> };
type Arqueo = { fondo: string; efectivo_cobrado: string; esperado: string; cantidad_pagos: number };

const num = (v: string | number | null | undefined) => Number(v ?? 0);

/** La cuenta del servidor con los cobros aún sin enviar ya descontados (y cerrada si quedó en cero). */
function vistaConCobros(p: Pedido, cobrado: number): Pedido {
  const pendiente = Math.max(num(p.cuenta.pendiente) - cobrado, 0);
  return {
    ...p,
    estado: pendiente === 0 ? "cerrado" : p.estado,
    cuenta: { ...p.cuenta, pagado: String(num(p.cuenta.pagado) + cobrado), pendiente: String(pendiente) },
  };
}

export default function Caja({ sesion, alSalir }: { sesion: Sesion; alSalir: () => void }) {
  const [turno, setTurno] = useState<Turno | null | undefined>(undefined); // undefined = cargando
  const [error, setError] = useState("");
  const [cerrando, setCerrando] = useState(false);
  const [vista, setVista] = useState<"cobrar" | "cobradas" | "propinas">("cobrar");
  const [pedidoId, setPedidoId] = useState<string | null>(null);
  useState(() => fijarCajero(sesion.usuario.id));            // la copia local ya está disponible en la primera pantalla
  useEffect(() => { iniciarPagos(sesion.usuario.id); }, [sesion.usuario.id]);
  const { cola } = usePagosSinConexion();

  const cargarTurno = useCallback(async () => {
    try {
      const t = await pedir<Turno>("/turnos/actual");
      guardarCache("turno", t);
      setTurno(t);
    } catch (e: any) {
      // 404 = no hay turno abierto: es un estado normal, no un error.
      if (e.estado === 404) { guardarCache("turno", null); setTurno(null); }
      // Sin red: se sigue con el turno que ya estaba abierto en esta caja.
      else if (e.estado === 0 && leerCache<Turno>("turno")) setTurno(leerCache<Turno>("turno"));
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
        {turno && (
          <button className="secundario" onClick={() => setCerrando(true)} disabled={cola.length > 0}
            title={cola.length > 0 ? "Hay cobros por enviar: espera a que se envíen para contar el cajón." : undefined}>
            Cerrar turno
          </button>
        )}
        <button className="secundario" onClick={alSalir}>Salir</button>
      </header>
      <AvisoPagos />
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
              <button className={`pestana ${vista === "cobradas" ? "activa" : ""}`} onClick={() => setVista("cobradas")}>Cobradas</button>
              <button className={`pestana ${vista === "propinas" ? "activa" : ""}`} onClick={() => setVista("propinas")}>Propinas</button>
            </nav>
            {vista === "cobrar" ? <PorCobrar alAbrir={setPedidoId} />
              : vista === "cobradas" ? <Cobradas esAdmin={sesion.usuario.roles.includes("administrador")} />
              : <Propinas />}
          </>
        )}
      </main>
      {cerrando && turno && <CerrarTurno turno={turno} alCerrar={() => setCerrando(false)} alTerminar={() => { setCerrando(false); setTurno(null); }} />}
    </>
  );
}

/** Franja de estado: cobros anotados sin enviar y cobros que el servidor no aceptó. */
function AvisoPagos() {
  const { cola, rechazados, enviando } = usePagosSinConexion();
  if (cola.length === 0 && rechazados.length === 0) return null;
  return (
    <div className="franja-conexion">
      {cola.length > 0 && (
        <p className="aviso-offline" role="status">
          {enviando ? "Enviando cobros…" : `${cola.length} cobro${cola.length === 1 ? "" : "s"} guardado${cola.length === 1 ? "" : "s"} en la caja, por enviar`}{" "}
          <button className="secundario" onClick={() => enviarPagos()}>Reintentar</button>
        </p>
      )}
      {rechazados.length > 0 && (
        <div className="error" role="alert">
          <strong>El servidor no aceptó {rechazados.length === 1 ? "un cobro" : `${rechazados.length} cobros`}.</strong>{" "}
          El dinero ya lo recibiste: avisa al administrador para registrarlo.
          <ul>{rechazados.map((r) => <li key={r.pago_id}>{r.mesa ?? "Cuenta"} · {plata(r.monto)} — {r.error}</li>)}</ul>
          <button className="secundario" onClick={descartarRechazados}>Entendido</button>
        </div>
      )}
    </div>
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
  const [mesas, setMesas] = useState<Mesa[] | null>(() => leerCache<Mesa[]>("mesas"));
  const [error, setError] = useState("");
  const [todas, setTodas] = useState(false);
  const { cola } = usePagosSinConexion();
  const cargar = useCallback(async () => {
    try {
      const m = await pedir<Mesa[]>("/mesas");
      guardarCache("mesas", m);
      setMesas(m);
      setError("");
      // Se guarda cada cuenta pedida para poder cobrarla aunque se caiga la red antes de abrirla.
      m.filter((x) => x.pedido_id && x.estado === "cuenta_pedida").forEach((x) => {
        pedir<Pedido>(`/pedidos/${x.pedido_id}`).then((p) => guardarCache("caja_pedido_" + x.pedido_id, p)).catch(() => {});
      });
    } catch (e: any) {
      // Sin red se muestra la última lista que se vio.
      setError(e instanceof ErrorApi && e.estado === 0 ? "Sin conexión: mostrando la última lista." : e.message);
    }
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
              <small>
                {cola.some((p) => p.pedido_id === m.pedido_id) ? "Cobro por enviar" : m.estado === "cuenta_pedida" ? "Pidió la cuenta" : "Abierta"}
              </small>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

// ── Cobrar una cuenta ───────────────────────────────────────
function Cobro({ pedidoId, alVolver }: { pedidoId: string; alVolver: () => void }) {
  const [servidor, setPedido] = useState<Pedido | null>(() => leerCache<Pedido>("caja_pedido_" + pedidoId));
  const [terminales, setTerminales] = useState<Terminal[]>(() => leerCache<Terminal[]>("terminales") ?? []);
  const [pctSugerido, setPctSugerido] = useState<number>(10);
  const { cola } = usePagosSinConexion();
  const enviadosLocal = pendienteDeEnvio(pedidoId, cola);
  // La cuenta que se muestra = la del servidor menos lo ya cobrado que aún no viajó.
  const pedido = servidor && enviadosLocal > 0 ? vistaConCobros(servidor, enviadosLocal) : servidor;
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
      guardarCache("caja_pedido_" + pedidoId, p);
      setPedido(p);
      setMonto((m) => (m === "" ? String(Math.max(num(p.cuenta.pendiente) - pendienteDeEnvio(pedidoId, colaActual()), 0)) : m));
    } catch (e: any) {
      if (!(e instanceof ErrorApi && e.estado === 0)) { setError(e.message); return; }
      // Sin red: el monto sugerido sale de la última cuenta vista menos lo ya cobrado sin enviar.
      const ultima = leerCache<Pedido>("caja_pedido_" + pedidoId);
      if (ultima) setMonto((m) => (m === "" ? String(Math.max(num(ultima.cuenta.pendiente) - pendienteDeEnvio(pedidoId, colaActual()), 0)) : m));
    }
  }, [pedidoId]);
  useEffect(() => {
    recargar();
    setTerminalId(String(leerCache<Terminal[]>("terminales")?.[0]?.id ?? ""));
    pedir<Terminal[]>("/terminales").then((t) => { guardarCache("terminales", t); setTerminales(t); setTerminalId(String(t[0]?.id ?? "")); }).catch(() => {});
    pedir<{ propina_sugerida_pct: string | number }>("/configuracion/cobro").then((c) => setPctSugerido(num(c.propina_sugerida_pct))).catch(() => {});
  }, [recargar]);

  // Ejecuta una acción de la cuenta; al terminar vuelve a pedir la cuenta y deja el monto al pendiente.
  const hacer = async (fn: () => Promise<unknown>, ok = "") => {
    setOcupado(true); setError(""); setAviso("");
    try { await fn(); if (ok) setAviso(ok); setMonto(""); } catch (e: any) { setError(e.message); } finally { setOcupado(false); recargar(); }
  };
  const propina = (m: number | null) => hacer(() => pedir(`/pedidos/${pedidoId}/propina`, { json: m === null ? {} : { monto: String(m) } }), "Propina anotada.");
  const [pidePin, setPidePin] = useState(false);
  const aplicarDescuento = async (sup?: { supervisor_id: number; pin_supervisor: string }) => {
    setOcupado(true); setError(""); setAviso("");
    try {
      await pedir(`/pedidos/${pedidoId}/descuento`, { json: { porcentaje: descuento, ...sup } });
      setAviso("Descuento aplicado.");
      setPidePin(false);
    } catch (e: any) {
      // Si pasa del tope del cajero, la API pide el PIN de un supervisor: se abre el diálogo para teclearlo.
      if (!sup && /PIN de un supervisor/i.test(e.message)) setPidePin(true);
      else { setError(e.message); if (sup) throw e; }
    } finally { setOcupado(false); recargar(); }
  };
  const cobrar = (ev: React.FormEvent) => {
    ev.preventDefault();
    // Se valida aquí lo que el servidor validaría, porque sin red nadie lo revisa antes de entregar el recibo.
    if (num(monto) <= 0) { setError("El monto debe ser mayor que cero."); return; }
    if (pedido && num(monto) > num(pedido.cuenta.pendiente)) { setError("El monto supera lo pendiente de la cuenta."); return; }
    if (medio === "efectivo" && recibido && num(recibido) < num(monto)) { setError("Lo recibido no alcanza para el monto a cobrar."); return; }
    const cuerpo = {
      medio, monto, pago_id: nuevoId(),
      recibido: medio === "efectivo" && recibido ? recibido : null,
      numero_operacion: medio !== "efectivo" ? operacion.trim() : null,
      terminal_id: medio === "tarjeta" ? Number(terminalId) : null,
    };
    hacer(async () => {
      try {
        const r = await pedir<Pago>(`/pedidos/${pedidoId}/pagos`, { json: cuerpo });
        setUltimo(r);
      } catch (e) {
        // Sin red: el cobro se anota en la caja con su número único y viaja solo cuando vuelva la red.
        if (!(e instanceof ErrorApi && e.estado === 0)) throw e;
        anotarPago({ pago_id: cuerpo.pago_id, pedido_id: pedidoId, mesa: pedido?.mesa ?? null, medio, monto, json: cuerpo });
        setUltimo({ vuelto: medio === "efectivo" && recibido ? String(num(recibido) - num(monto)) : null, pedido_estado: "", documento_estado: null, documento_folio: null, cuenta: pedido!.cuenta });
        setAviso("Sin conexión: cobro guardado en la caja. Se enviará solo al volver la red.");
      }
      setRecibido(""); setOperacion("");
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
            {enviadosLocal > 0 && <p className="aviso-offline">Cobro guardado en la caja: se envía solo al volver la red.</p>}
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
              <button className="secundario" disabled={ocupado || !descuento} onClick={() => aplicarDescuento()}>Aplicar</button>
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
      {pidePin && <PinSupervisorDialogo porcentaje={descuento} alCerrar={() => setPidePin(false)} alAutorizar={(sup) => aplicarDescuento(sup)} />}
    </div>
  );
}

/** Un supervisor (administrador con PIN) teclea su PIN para autorizar un descuento sobre el tope del cajero. */
function PinSupervisorDialogo({ porcentaje, alCerrar, alAutorizar }: {
  porcentaje: string; alCerrar: () => void; alAutorizar: (s: { supervisor_id: number; pin_supervisor: string }) => Promise<void>;
}) {
  const [sups, setSups] = useState<Supervisor[] | null>(null);
  const [sup, setSup] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    pedir<Supervisor[]>("/supervisores").then((l) => { setSups(l); setSup(String(l[0]?.id ?? "")); }).catch((e) => setError(e.message));
  }, []);
  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError("");
    try { await alAutorizar({ supervisor_id: Number(sup), pin_supervisor: pin }); } catch (e: any) { setError(e.message); setPin(""); }
  };
  return (
    <Dialogo titulo="Autoriza un supervisor" alCerrar={alCerrar}>
      <p className="suave">Un descuento de {porcentaje}% pasa de tu tope. Pide a un supervisor que teclee su PIN.</p>
      {sups && sups.length === 0 ? (
        <p className="error">Ningún administrador tiene PIN todavía. Pídele que lo cree en Configuración.</p>
      ) : (
        <form onSubmit={enviar} style={{ display: "grid", gap: 8 }}>
          <label className="campo"><span>Supervisor</span>
            <select value={sup} onChange={(e) => setSup(e.target.value)}>{(sups ?? []).map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}</select>
          </label>
          <label className="campo"><span>PIN</span>
            <input type="password" inputMode="numeric" maxLength={6} value={pin} onChange={(e) => setPin(e.target.value)} autoComplete="off" required />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button type="submit" disabled={!sup || pin.length < 4}>Autorizar descuento</button>
        </form>
      )}
    </Dialogo>
  );
}

// ── Cuentas cobradas y devoluciones ─────────────────────────
const NOMBRE_MEDIO: Record<string, string> = { efectivo: "Efectivo", tarjeta: "Tarjeta", transferencia: "Transferencia" };

function Cobradas({ esAdmin }: { esAdmin: boolean }) {
  const [lista, setLista] = useState<Cobrada[] | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [devolviendo, setDevolviendo] = useState<Cobrada | null>(null);
  const cargar = useCallback(() => pedir<Cobrada[]>("/cobradas").then((l) => { setLista(l); setError(""); }).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); }, [cargar]);
  return (
    <>
      <div className="encabezado"><h1>Cuentas cobradas</h1><span className="suave">Últimas 24 horas</span></div>
      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="exito" role="status">{aviso}</p>}
      {!lista ? <p className="suave">Cargando…</p> : lista.length === 0 ? <p className="suave">No hay cuentas cobradas en las últimas 24 horas.</p> : (
        <ul className="lineas">
          {lista.map((c) => {
            const devuelto = Object.values(c.devuelto).reduce((s, v) => s + num(v), 0);
            return (
              <li key={c.pedido_id} className="linea">
                <div>
                  <strong>{c.mesa ?? "Cuenta"} · {plata(c.total)}</strong>
                  <div className="suave">{c.cerrado_en ? new Date(c.cerrado_en).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" }) : ""}
                    {devuelto > 0 ? ` · devuelto ${plata(devuelto)}` : ""}</div>
                </div>
                <button className="secundario" onClick={() => { setAviso(""); setDevolviendo(c); }}>Devolver dinero</button>
              </li>
            );
          })}
        </ul>
      )}
      {devolviendo && (
        <DialogoDevolucion cobrada={devolviendo} esAdmin={esAdmin} alCerrar={() => setDevolviendo(null)}
          alTerminar={(msg) => { setDevolviendo(null); setAviso(msg); cargar(); }} />
      )}
    </>
  );
}

/** Devolver dinero de una cuenta cobrada: por el mismo medio de pago, con motivo y (el cajero) con el PIN de un supervisor. */
function DialogoDevolucion({ cobrada, esAdmin, alCerrar, alTerminar }: {
  cobrada: Cobrada; esAdmin: boolean; alCerrar: () => void; alTerminar: (mensaje: string) => void;
}) {
  const quedan = (m: string) => Math.max(num(cobrada.pagado[m]) - num(cobrada.devuelto[m]), 0);
  const medios = ["efectivo", "tarjeta", "transferencia"].filter((m) => quedan(m) > 0);
  const [medio, setMedio] = useState(medios[0] ?? "efectivo");
  const [monto, setMonto] = useState(medios[0] ? String(quedan(medios[0])) : "");
  const [motivo, setMotivo] = useState("");
  const [operacion, setOperacion] = useState("");
  const [anular, setAnular] = useState(false);
  const [sups, setSups] = useState<Supervisor[]>([]);
  const [sup, setSup] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => {
    if (esAdmin) return;
    pedir<Supervisor[]>("/supervisores").then((l) => { setSups(l); setSup(String(l[0]?.id ?? "")); }).catch((e) => setError(e.message));
  }, [esAdmin]);
  const cambiarMedio = (m: string) => { setMedio(m); setMonto(String(quedan(m))); };

  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError(""); setOcupado(true);
    try {
      const r = await pedir<{ monto: string; nota_credito_estado: string | null }>(`/pedidos/${cobrada.pedido_id}/devoluciones`, {
        json: {
          medio, monto, motivo: motivo.trim(), anular_documento: anular,
          numero_operacion: medio !== "efectivo" ? operacion.trim() : null,
          ...(esAdmin ? {} : { supervisor_id: Number(sup), pin_supervisor: pin }),
        },
      });
      const nota = r.nota_credito_estado;
      alTerminar(`Devolución registrada: ${plata(r.monto)} por ${NOMBRE_MEDIO[medio].toLowerCase()}.` +
        (nota === "emitido" ? " Nota de crédito emitida." : nota === "pendiente" ? " La nota de crédito quedó pendiente." :
         nota === "no_aplica" ? " (La nota de crédito se emite al devolver toda la cuenta.)" : nota === "no_disponible" ? " No se pudo emitir la nota de crédito: hazla desde facturación." : ""));
    } catch (e: any) {
      setError(e.message); setPin("");
    } finally { setOcupado(false); }
  };

  return (
    <Dialogo titulo={`Devolver dinero · ${cobrada.mesa ?? "Cuenta"}`} alCerrar={alCerrar}>
      {medios.length === 0 ? <p className="suave">Ya se devolvió todo lo cobrado de esta cuenta.</p> : (
        <form onSubmit={enviar} style={{ display: "grid", gap: 8 }}>
          <label className="campo"><span>Por dónde se devuelve</span>
            <select value={medio} onChange={(e) => cambiarMedio(e.target.value)}>
              {medios.map((m) => <option key={m} value={m}>{NOMBRE_MEDIO[m]} (hasta {plata(quedan(m))})</option>)}
            </select>
          </label>
          <label className="campo"><span>Monto</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={monto} onChange={(e) => setMonto(e.target.value)} required />
            {medio === "efectivo" && <small>Sale del cajón: baja lo esperado en tu arqueo.</small>}
          </label>
          {medio !== "efectivo" && (
            <label className="campo"><span>Número de operación de la devolución</span>
              <input value={operacion} onChange={(e) => setOperacion(e.target.value)} required maxLength={60} />
            </label>
          )}
          <label className="campo"><span>Motivo</span>
            <input value={motivo} onChange={(e) => setMotivo(e.target.value)} required minLength={3} maxLength={200} placeholder="Ej.: plato frío, cobro duplicado" />
          </label>
          <label className="opcion"><input type="checkbox" checked={anular} onChange={(e) => setAnular(e.target.checked)} />
            <span>Emitir nota de crédito si se devuelve toda la cuenta</span></label>
          {!esAdmin && (
            <>
              <label className="campo"><span>Supervisor</span>
                <select value={sup} onChange={(e) => setSup(e.target.value)}>{sups.map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}</select>
              </label>
              <label className="campo"><span>PIN del supervisor</span>
                <input type="password" inputMode="numeric" maxLength={6} value={pin} onChange={(e) => setPin(e.target.value)} autoComplete="off" required />
              </label>
            </>
          )}
          {error && <p className="error" role="alert">{error}</p>}
          <button type="submit" disabled={ocupado || !monto || !motivo.trim() || (!esAdmin && (!sup || pin.length < 4))}>Devolver {monto ? plata(monto) : ""}</button>
        </form>
      )}
    </Dialogo>
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
