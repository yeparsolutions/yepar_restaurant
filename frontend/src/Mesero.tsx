// ============================================================
// YEPAR RESTAURANT — frontend/src/Mesero.tsx
// La pantalla del mesero en la tablet: plano de mesas → pedido de la mesa → carta → enviar a cocina.
// Analogía: es la libreta del mesero. Cada plato se anota en la libreta (estado "tomada") y solo
// cuando toca "Enviar a cocina" las hojas viajan a la cocina; antes de eso se pueden tachar sin costo.
// ============================================================
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ErrorApi, pedir, type Sesion } from "./api";
import { Marca } from "./App";
import {
  descartarRechazadas, descartarSiNoSalio, encolar, fijarUsuario, guardarCache, iniciarSinConexion, leerCache, nuevoId, useSinConexion,
  vaciarCola, type Operacion,
} from "./sinConexion";

export { nuevoId };

// ── Tipos que devuelve la API ───────────────────────────────
type EstadoMesa = "libre" | "ocupada" | "lista" | "cuenta_pedida";
type Mesa = {
  mesa_id: number; nombre: string; estado: EstadoMesa; pedido_id: string | null; lineas_listas: number;
  capacidad: number | null; pos_x: number | null; pos_y: number | null; ancho: number | null; alto: number | null; forma: string | null;
};
type Opcion = { id: number; nombre: string; precio: string | null };
type Falta = { nombre: string; agotado_manual?: boolean };
type Plato = {
  item_id: number; nombre: string; categoria: string | null; precio_venta: string | null; foto_url: string | null;
  estacion: string; alcanza: boolean; faltas: Falta[]; removibles: Opcion[]; extras: Opcion[];
};
type Linea = {
  pendiente?: boolean;                       // anotada en esta tablet, todavía sin confirmar por el servidor
  id: string; item_id: number; nombre: string; cantidad: number; precio_unitario: string; comensal: number | null;
  nota: string | null; estado: string; estacion: string; quitados: number[]; extras: number[]; total: string;
};
type Cuenta = { subtotal: string; descuento: string; propina: string; total: string; pagado: string; pendiente: string };
type Pedido = { id: string; mesa: string | null; estado: string; comensales: number | null; lineas: Linea[]; cuenta: Cuenta };

const ETIQUETA_ESTADO: Record<string, string> = {
  tomada: "En la libreta", enviada: "En cocina", en_preparacion: "Preparando", lista: "¡Lista!", entregada: "Entregada", cancelada: "Cancelada",
};
const ESTADOS_MESA: Record<EstadoMesa, string> = { libre: "Libre", ocupada: "Ocupada", lista: "Plato listo", cuenta_pedida: "Pidió la cuenta" };

export const plata = (v: string | number | null | undefined) => {
  const n = Number(v ?? 0);
  return "$" + n.toLocaleString("es-CL", { maximumFractionDigits: 2 });
};
// La API entrega ids de lo quitado/agregado; los nombres salen de la carta.
const nombresDe = (ids: number[], opciones: Opcion[]) => ids.map((i) => opciones.find((o) => o.id === i)?.nombre ?? "…").join(", ");

// ── Lo anotado sin confirmar se muestra encima de lo que sabe el servidor ──
const CEROS: Cuenta = { subtotal: "0", descuento: "0", propina: "0", total: "0", pagado: "0", pendiente: "0" };

/** El pedido tal como lo ve el mesero: la última copia del servidor + las operaciones que aún no se sincronizaron. */
function pedidoConPendientes(base: Pedido | null, ops: Operacion[], id: string, carta: Plato[], mesas: Mesa[]): Pedido | null {
  let p: Pedido | null = base ? structuredClone(base) : null;
  let tocado = false;
  for (const o of ops) {
    const d = o.datos as Record<string, any>;
    if (o.tipo === "abrir_pedido" && d.pedido_id === id && !p) {
      p = { id, mesa: mesas.find((m) => m.mesa_id === d.mesa_id)?.nombre ?? null, estado: "abierto", comensales: d.comensales ?? null, lineas: [], cuenta: { ...CEROS } };
      tocado = true;
    } else if (!p) {
      continue;
    } else if (o.tipo === "tomar_linea" && d.pedido_id === id) {
      const plato = carta.find((x) => x.item_id === d.item_id);
      const extras = (d.extra_ids as number[] ?? []).map((e) => plato?.extras.find((x) => x.id === e));
      const unit = Number(plato?.precio_venta ?? 0);
      const total = (unit + extras.reduce((t, e) => t + Number(e?.precio ?? 0), 0)) * d.cantidad;
      p.lineas.push({
        id: d.linea_id, item_id: d.item_id, nombre: plato?.nombre ?? "Plato", cantidad: d.cantidad, precio_unitario: String(unit),
        comensal: d.comensal ?? null, nota: d.nota ?? null, estado: "tomada", estacion: plato?.estacion ?? "cocina",
        quitados: d.sin_ingredientes ?? [], extras: d.extra_ids ?? [], total: String(total), pendiente: true,
      });
      tocado = true;
    } else if (o.tipo === "quitar_linea") {
      const antes = p.lineas.length;
      p.lineas = p.lineas.filter((l) => l.id !== d.linea_id);
      tocado = tocado || p.lineas.length !== antes;
    } else if (o.tipo === "enviar" && d.pedido_id === id) {
      p.lineas.forEach((l) => { if (l.estado === "tomada") { l.estado = "enviada"; l.pendiente = true; } });
      tocado = true;
    } else if (o.tipo === "cancelar_linea") {
      p.lineas.forEach((l) => { if (l.id === d.linea_id) { l.estado = "cancelada"; l.pendiente = true; } });
      tocado = true;
    } else if (o.tipo === "pedir_cuenta" && d.pedido_id === id) {
      p.estado = "cuenta_pedida"; tocado = true;
    } else if (o.tipo === "anular_pedido" && d.pedido_id === id) {
      p.estado = "anulado"; tocado = true;
    }
  }
  if (p && tocado) {
    // Los totales se recalculan con lo que hay; propina y descuento siguen como los dejó el servidor.
    const subtotal = p.lineas.filter((l) => l.estado !== "cancelada").reduce((t, l) => t + Number(l.total), 0);
    const total = subtotal - Number(p.cuenta.descuento) + Number(p.cuenta.propina);
    p.cuenta = { ...p.cuenta, subtotal: String(subtotal), total: String(total), pendiente: String(total - Number(p.cuenta.pagado)) };
  }
  return p;
}

/** El plano con las mesas abiertas o con cuenta pedida sin conexión ya marcadas. */
function mesasConPendientes(mesas: Mesa[], ops: Operacion[]): Mesa[] {
  let m = mesas.map((x) => ({ ...x }));
  for (const o of ops) {
    const d = o.datos as Record<string, any>;
    if (o.tipo === "abrir_pedido") m = m.map((x) => (x.mesa_id === d.mesa_id && !x.pedido_id ? { ...x, estado: "ocupada" as EstadoMesa, pedido_id: d.pedido_id } : x));
    else if (o.tipo === "pedir_cuenta") m = m.map((x) => (x.pedido_id === d.pedido_id ? { ...x, estado: "cuenta_pedida" as EstadoMesa } : x));
    else if (o.tipo === "anular_pedido") m = m.map((x) => (x.pedido_id === d.pedido_id ? { ...x, estado: "libre" as EstadoMesa, pedido_id: null } : x));
  }
  return m;
}

/** Franja de estado: sin conexión, cambios por enviar y operaciones que el servidor rechazó. */
function AvisoConexion() {
  const { cola, rechazadas, enLinea, enviando } = useSinConexion();
  if (enLinea && cola.length === 0 && rechazadas.length === 0) return null;
  return (
    <div className="franja-conexion">
      {!enLinea && <p className="aviso-offline" role="status">Sin conexión. Sigue trabajando: tus pedidos se guardan en la tablet y se envían solos al volver la red.</p>}
      {cola.length > 0 && (
        <p className="aviso-cola" role="status">
          {enviando ? "Enviando…" : `${cola.length} cambio${cola.length === 1 ? "" : "s"} por enviar`}{" "}
          <button className="secundario" onClick={() => vaciarCola()}>Reintentar</button>
        </p>
      )}
      {rechazadas.length > 0 && (
        <div className="error" role="alert">
          <strong>El servidor no aceptó {rechazadas.length === 1 ? "un cambio" : `${rechazadas.length} cambios`}:</strong>
          <ul>{rechazadas.map((r) => <li key={r.op_id}>{r.error}</li>)}</ul>
          <button className="secundario" onClick={descartarRechazadas}>Entendido</button>
        </div>
      )}
    </div>
  );
}

export default function Mesero({ sesion, alSalir }: { sesion: Sesion; alSalir: () => void }) {
  const [pedidoId, setPedidoId] = useState<string | null>(null);
  useState(() => fijarUsuario(sesion.usuario.id));        // antes del primer dibujo: así la pantalla ya lee su copia local
  useEffect(() => { iniciarSinConexion(sesion.usuario.id); }, [sesion.usuario.id]);
  return (
    <>
      <header className="barra">
        <Marca />
        <span className="suave">Mesero · {sesion.usuario.nombre}</span>
        <span style={{ flex: 1 }} />
        <button className="secundario" onClick={alSalir}>Salir</button>
      </header>
      <AvisoConexion />
      <main className="contenido">
        {pedidoId ? <VistaPedido pedidoId={pedidoId} alVolver={() => setPedidoId(null)} /> : <Plano alAbrir={setPedidoId} />}
      </main>
    </>
  );
}

// ── Plano de mesas ──────────────────────────────────────────
function Plano({ alAbrir }: { alAbrir: (pedidoId: string) => void }) {
  const [servidor, setMesas] = useState<Mesa[] | null>(() => leerCache<Mesa[]>("mesas"));
  const [error, setError] = useState("");
  const [comensales, setComensales] = useState<Mesa | null>(null);
  const listasAntes = useRef<Set<number>>(new Set());
  const { cola } = useSinConexion();
  const mesas = useMemo(() => (servidor ? mesasConPendientes(servidor, cola) : null), [servidor, cola]);

  const cargar = useCallback(async () => {
    try {
      const m = await pedir<Mesa[]>("/mesas");
      guardarCache("mesas", m);
      // Avisa con vibración cuando una mesa pasa a "lista" (la cocina terminó un plato).
      const ahora = new Set(m.filter((x) => x.estado === "lista").map((x) => x.mesa_id));
      if ([...ahora].some((id) => !listasAntes.current.has(id))) navigator.vibrate?.([200, 100, 200]);
      listasAntes.current = ahora;
      setMesas(m);
      setError("");
    } catch (e: any) {
      // Sin red se sigue con la última copia del plano; solo es un error si nunca se pudo cargar.
      if (!(e instanceof ErrorApi && e.estado === 0)) setError(e.message);
    }
  }, []);
  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 8000);
    return () => clearInterval(t);
  }, [cargar]);
  // Cuando la cola termina de sincronizar, se vuelve a pedir el plano para ver el estado real.
  useEffect(() => { cargar(); }, [cola.length, cargar]);

  // Abrir una mesa se anota en la libreta: funciona igual con o sin red.
  const abrir = (mesa: Mesa, n: number | null) => {
    const id = nuevoId();
    encolar("abrir_pedido", { mesa_id: mesa.mesa_id, comensales: n, pedido_id: id });
    setComensales(null);
    alAbrir(id);
  };
  const tocar = (mesa: Mesa) => {
    if (mesa.pedido_id) alAbrir(mesa.pedido_id);
    else setComensales(mesa);
  };

  if (!mesas) return <p className="suave">{error || "Cargando mesas…"}</p>;
  const ancho = Math.max(320, ...mesas.map((m) => (m.pos_x ?? 0) + (m.ancho ?? 90) + 20));
  const alto = Math.max(240, ...mesas.map((m) => (m.pos_y ?? 0) + (m.alto ?? 90) + 20));

  return (
    <>
      <h1>Mesas</h1>
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="leyenda">
        {(Object.keys(ESTADOS_MESA) as EstadoMesa[]).map((e) => (
          <li key={e}><i className={`punto ${e}`} /> {ESTADOS_MESA[e]}</li>
        ))}
      </ul>
      {mesas.length === 0 ? (
        <p className="suave">Todavía no hay mesas. Pídele al administrador que arme el plano en Configuración.</p>
      ) : (
        <div className="plano-marco">
          <div className="plano" style={{ width: ancho, height: alto }}>
            {mesas.map((m, i) => (
              <button
                key={m.mesa_id}
                className={`mesa-tab ${m.estado} ${m.forma === "redonda" ? "redonda" : ""}`}
                style={{
                  left: m.pos_x ?? 10 + (i % 4) * 110, top: m.pos_y ?? 10 + Math.floor(i / 4) * 110,
                  width: m.ancho ?? 90, height: m.alto ?? 90,
                }}
                onClick={() => tocar(m)}
                aria-label={`${m.nombre}, ${ESTADOS_MESA[m.estado]}`}
              >
                <strong>{m.nombre}</strong>
                <small>{m.estado === "lista" ? `${m.lineas_listas} lista${m.lineas_listas === 1 ? "" : "s"}` : ESTADOS_MESA[m.estado]}</small>
              </button>
            ))}
          </div>
        </div>
      )}
      {comensales && (
        <Dialogo titulo={`Abrir ${comensales.nombre}`} alCerrar={() => setComensales(null)}>
          <p className="suave">¿Cuántas personas son?</p>
          <div className="numeros">
            {Array.from({ length: Math.min(12, Math.max(comensales.capacidad ?? 8, 4)) }, (_, i) => i + 1).map((n) => (
              <button key={n} className="secundario" onClick={() => abrir(comensales, n)}>{n}</button>
            ))}
          </div>
          <button className="secundario" onClick={() => abrir(comensales, null)}>Sin indicar</button>
        </Dialogo>
      )}
    </>
  );
}

// ── Pedido de una mesa ──────────────────────────────────────
function VistaPedido({ pedidoId, alVolver }: { pedidoId: string; alVolver: () => void }) {
  const [servidor, setServidor] = useState<Pedido | null>(() => leerCache<Pedido>("pedido_" + pedidoId));
  const [carta, setCarta] = useState<Plato[]>(() => leerCache<Plato[]>("carta") ?? []);
  const { cola, enLinea } = useSinConexion();
  const pedido = useMemo(() => pedidoConPendientes(servidor, cola, pedidoId, carta, leerCache<Mesa[]>("mesas") ?? []), [servidor, cola, pedidoId, carta]);
  const [categoria, setCategoria] = useState("Todo");
  const [busca, setBusca] = useState("");
  const [elegido, setElegido] = useState<Plato | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const recargar = useCallback(async () => {
    try {
      const p = await pedir<Pedido>(`/pedidos/${pedidoId}`);
      guardarCache("pedido_" + pedidoId, p);
      setServidor(p);
    } catch (e: any) {
      // 404 = la mesa se abrió sin conexión y todavía no llegó al servidor: se muestra lo local.
      // Sin red también se sigue con lo último que se vio.
      if (e instanceof ErrorApi && (e.estado === 0 || e.estado === 404)) return;
      setError(e.message);
    }
  }, [pedidoId]);
  useEffect(() => {
    recargar();
    pedir<Plato[]>("/carta").then((c) => { guardarCache("carta", c); setCarta(c); }).catch((e) => {
      if (!(e instanceof ErrorApi && e.estado === 0)) setError(e.message);
    });
    const t = setInterval(recargar, 8000);
    return () => clearInterval(t);
  }, [recargar]);
  // Al terminar de sincronizar se vuelve a pedir el pedido para ver el estado real.
  useEffect(() => { recargar(); }, [cola.length, recargar]);

  const categorias = useMemo(() => ["Todo", ...Array.from(new Set(carta.map((p) => p.categoria ?? "Otros")))], [carta]);
  const visibles = carta.filter(
    (p) => (categoria === "Todo" || (p.categoria ?? "Otros") === categoria) && p.nombre.toLowerCase().includes(busca.trim().toLowerCase()),
  );

  // Ejecuta una acción, muestra el error si falla y siempre refresca el pedido.
  const hacer = async (fn: () => Promise<unknown>, ok = "") => {
    setOcupado(true);
    setError("");
    setAviso("");
    try {
      await fn();
      if (ok) setAviso(ok);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setOcupado(false);
      recargar();
    }
  };

  // Todo lo que anota el mesero va a la libreta (cola): funciona igual con o sin red y se envía solo.
  const donde = enLinea ? "" : " Se enviará al volver la conexión.";
  const agregar = (datos: { cantidad: number; comensal: number | null; sin: number[]; extras: number[]; nota: string }, plato: Plato) => {
    encolar("tomar_linea", {
      pedido_id: pedidoId, item_id: plato.item_id, cantidad: datos.cantidad, comensal: datos.comensal, sin_ingredientes: datos.sin,
      extra_ids: datos.extras, nota: datos.nota || null, linea_id: nuevoId(),
    });
    setElegido(null);
    setError("");
    // El semáforo viene de la carta que ya tiene la tablet: solo avisa, nunca bloquea.
    setAviso(plato.alcanza ? `${plato.nombre} anotado.` : `Ojo: a ${plato.nombre} le falta ${plato.faltas.map((f) => f.nombre).join(", ")}. Igual quedó anotado.`);
  };

  const enviar = () => {
    encolar("enviar", { pedido_id: pedidoId });
    setError("");
    setAviso(`Enviado a cocina (${enLibreta.length} plato${enLibreta.length === 1 ? "" : "s"}).${donde}`);
  };

  const [traspaso, setTraspaso] = useState(false);
  // Anular va a la libreta (funciona sin red); pasar la mesa necesita al servidor en el momento.
  const anularPedido = () => {
    if (!window.confirm("¿Anular este pedido? Solo se puede si no se envió ningún plato a cocina.")) return;
    encolar("anular_pedido", { pedido_id: pedidoId });
    alVolver();
  };
  const pedirCuenta = () => {
    encolar("pedir_cuenta", { pedido_id: pedidoId });
    setError("");
    setAviso(`Cuenta pedida. La caja la recibirá.${donde}`);
  };
  const borrar = (l: Linea) => {
    // Si ese plato todavía no salió de la tablet, basta con sacarlo de la cola; si no, se anota que se quitó.
    if (!descartarSiNoSalio((o) => o.tipo === "tomar_linea" && o.datos.linea_id === l.id)) encolar("quitar_linea", { linea_id: l.id });
  };
  const cancelar = (l: Linea) => {
    if (window.confirm(`¿Cancelar "${l.nombre}"? Si cocina ya lo preparó, quedará como merma.`)) {
      encolar("cancelar_linea", { linea_id: l.id });
      setAviso(`${l.nombre} cancelado.${donde}`);
    }
  };
  const entregar = (l: Linea) => hacer(() => pedir(`/lineas/${l.id}/entregar`, { metodo: "POST" }), `${l.nombre} entregado.`);

  if (!pedido) return <p className="suave">{error || "Abriendo la mesa…"}</p>;
  const enLibreta = pedido.lineas.filter((l) => l.estado === "tomada");
  const abierto = pedido.estado === "abierto";

  return (
    <div className="pedido-grid">
      <section>
        <div className="encabezado">
          <h1>{pedido.mesa ?? "Pedido"}{pedido.comensales ? ` · ${pedido.comensales} pers.` : ""}</h1>
          <button className="secundario" onClick={alVolver}>← Mesas</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {aviso && !error && <p className="exito" role="status">{aviso}</p>}

        <ul className="lineas">
          {pedido.lineas.length === 0 && <li className="suave">Aún no hay platos. Elige uno de la carta.</li>}
          {pedido.lineas.map((l) => (
            <li key={l.id} className={`linea ${l.estado}`}>
              <div>
                <strong>{l.cantidad}× {l.nombre}</strong>{" "}
                <span className={`estado ${l.estado}`}>{ETIQUETA_ESTADO[l.estado] ?? l.estado}</span>{l.pendiente && <span className="pendiente" title="Se enviará al volver la conexión"> ⏳</span>}
                <small className="suave">
                  {l.comensal ? `Persona ${l.comensal}` : ""}
                  {l.quitados.length ? ` · sin ${nombresDe(l.quitados, carta.find((p) => p.item_id === l.item_id)?.removibles ?? [])}` : ""}
                  {l.extras.length ? ` · con ${nombresDe(l.extras, carta.find((p) => p.item_id === l.item_id)?.extras ?? [])}` : ""}
                  {l.nota ? ` · “${l.nota}”` : ""}
                </small>
              </div>
              <span>{plata(l.total)}</span>
              {l.estado === "tomada" && <button className="secundario" disabled={ocupado} onClick={() => borrar(l)} aria-label={`Quitar ${l.nombre}`}>✕</button>}
              {l.estado === "lista" && <button disabled={ocupado} onClick={() => entregar(l)}>Entregar</button>}
              {["enviada", "en_preparacion"].includes(l.estado) && <button className="secundario" disabled={ocupado} onClick={() => cancelar(l)}>Cancelar</button>}
            </li>
          ))}
        </ul>

        <div className="totales">
          <span>Total</span><strong>{plata(pedido.cuenta.total)}</strong>
        </div>
        {abierto ? (
          <div className="acciones">
            <button disabled={ocupado || enLibreta.length === 0} onClick={enviar}>Enviar a cocina ({enLibreta.length})</button>
            <button className="secundario" disabled={ocupado || pedido.lineas.length === 0} onClick={pedirCuenta}>Pedir la cuenta</button>
          </div>
        ) : pedido.estado === "cuenta_pedida" ? (
          <Propina pedidoId={pedidoId} propinaActual={pedido.cuenta.propina} sinRed={!enLinea} alCambiar={recargar} />
        ) : (
          <p className="suave">Esta cuenta está en estado «{pedido.estado}».</p>
        )}
        {(abierto || pedido.estado === "cuenta_pedida") && (
          <div className="acciones">
            <button className="secundario" onClick={() => setTraspaso(true)}>Pasar mesa a otro mesero</button>
            {abierto && <button className="secundario" disabled={pedido.lineas.some((l) => !["tomada", "cancelada"].includes(l.estado))} onClick={anularPedido}>Anular pedido</button>}
          </div>
        )}
      </section>

      {abierto && (
        <section>
          <h2 style={{ marginTop: 0 }}>Carta</h2>
          <input type="search" placeholder="Buscar plato…" value={busca} onChange={(e) => setBusca(e.target.value)} aria-label="Buscar plato" />
          <div className="categorias" role="tablist">
            {categorias.map((c) => (
              <button key={c} role="tab" aria-selected={c === categoria} className={`pestana ${c === categoria ? "activa" : ""}`} onClick={() => setCategoria(c)}>{c}</button>
            ))}
          </div>
          <div className="carta">
            {visibles.map((p) => (
              <button key={p.item_id} className={`plato ${p.alcanza ? "" : "falta"}`} onClick={() => setElegido(p)}>
                {p.foto_url ? <img src={p.foto_url} alt="" loading="lazy" /> : <span className="sinfoto" aria-hidden="true">🍽</span>}
                <strong>{p.nombre}</strong>
                <small>{plata(p.precio_venta)}</small>
                {!p.alcanza && <small className="aviso-falta">Falta {p.faltas.map((f) => f.nombre).join(", ")}</small>}
              </button>
            ))}
            {visibles.length === 0 && <p className="suave">No hay platos con ese filtro.</p>}
          </div>
        </section>
      )}

      {traspaso && (
        <DialogoTraspaso
          alCerrar={() => setTraspaso(false)}
          alPasar={async (id) => { await pedir(`/pedidos/${pedidoId}/traspaso`, { json: { nuevo_mesero_id: id } }); setTraspaso(false); alVolver(); }}
        />
      )}
      {elegido && (
        <DialogoPlato plato={elegido} comensales={pedido.comensales} ocupado={ocupado} alCerrar={() => setElegido(null)} alAgregar={(d) => agregar(d, elegido)} />
      )}
    </div>
  );
}

// ── Propina (la anota el mesero al pedir la cuenta) ─────────
function Propina({ pedidoId, propinaActual, sinRed, alCambiar }: { pedidoId: string; propinaActual: string; sinRed: boolean; alCambiar: () => void }) {
  const [otra, setOtra] = useState("");
  const [pct, setPct] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null);
  useEffect(() => {
    pedir<{ propina_sugerida_pct: string | number }>("/configuracion/cobro").then((c) => setPct(Number(c.propina_sugerida_pct))).catch(() => {});
  }, []);
  const anotar = async (monto: number | null) => {
    setMsg(null);
    try {
      await pedir(`/pedidos/${pedidoId}/propina`, { json: monto === null ? {} : { monto: String(monto) } });
      setMsg({ ok: true, texto: "Propina anotada." });
      alCambiar();
    } catch (e: any) {
      setMsg({ ok: false, texto: e.message });
    }
  };
  return (
    <div className="bloque">
      <p className="suave">La cuenta ya está pedida. Anota la propina que dejó el cliente (propina actual: <strong>{plata(propinaActual)}</strong>).</p>
      {sinRed && <p className="aviso-offline">Sin conexión: la propina se anota cuando vuelva la red.</p>}
      <div className="acciones">
        <button disabled={sinRed} onClick={() => anotar(null)}>Sugerida{pct !== null ? ` (${pct}%)` : ""}</button>
        <button className="secundario" disabled={sinRed} onClick={() => anotar(0)}>Sin propina</button>
      </div>
      <div className="en-linea">
        <input type="number" inputMode="decimal" min="0" placeholder="Otro monto" aria-label="Otro monto de propina" value={otra} onChange={(e) => setOtra(e.target.value)} />
        <button className="secundario" disabled={sinRed || !otra} onClick={() => anotar(Number(otra))}>Anotar</button>
      </div>
      {msg && <p className={msg.ok ? "exito" : "error"} role="status">{msg.texto}</p>}
    </div>
  );
}

// ── Pasar la mesa a otro mesero ─────────────────────────────
function DialogoTraspaso({ alCerrar, alPasar }: { alCerrar: () => void; alPasar: (id: number) => Promise<void> }) {
  const [meseros, setMeseros] = useState<{ id: number; nombre: string }[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { pedir<{ id: number; nombre: string }[]>("/meseros").then(setMeseros).catch((e) => setError(e.message)); }, []);
  const pasar = async (id: number) => {
    setError("");
    try { await alPasar(id); } catch (e: any) { setError(e.message); }
  };
  return (
    <Dialogo titulo="Pasar la mesa a…" alCerrar={alCerrar}>
      {error && <p className="error" role="alert">{error}</p>}
      {!meseros ? <p className="suave">Cargando…</p> : meseros.length === 0 ? (
        <p className="suave">No hay otros meseros activos en este local.</p>
      ) : (
        <ul className="insumos">
          {meseros.map((m) => (
            <li key={m.id}><span>{m.nombre}</span><button onClick={() => pasar(m.id)}>Pasar</button></li>
          ))}
        </ul>
      )}
    </Dialogo>
  );
}

// ── Elegir cómo se prepara un plato ─────────────────────────
function DialogoPlato({ plato, comensales, ocupado, alCerrar, alAgregar }: {
  plato: Plato; comensales: number | null; ocupado: boolean; alCerrar: () => void;
  alAgregar: (d: { cantidad: number; comensal: number | null; sin: number[]; extras: number[]; nota: string }) => void;
}) {
  const [cantidad, setCantidad] = useState(1);
  const [comensal, setComensal] = useState<number | null>(null);
  const [sin, setSin] = useState<number[]>([]);
  const [extras, setExtras] = useState<number[]>([]);
  const [nota, setNota] = useState("");
  const alternar = (lista: number[], set: (x: number[]) => void, id: number) =>
    set(lista.includes(id) ? lista.filter((x) => x !== id) : [...lista, id]);
  const precioExtras = plato.extras.filter((e) => extras.includes(e.id)).reduce((s, e) => s + Number(e.precio ?? 0), 0);
  const total = (Number(plato.precio_venta ?? 0) + precioExtras) * cantidad;

  return (
    <Dialogo titulo={plato.nombre} alCerrar={alCerrar}>
      {!plato.alcanza && <p className="error">Falta {plato.faltas.map((f) => f.nombre).join(", ")}. Puedes anotarlo igual, pero avisa al cliente.</p>}
      <div className="fila-cant">
        <button className="secundario" onClick={() => setCantidad(Math.max(1, cantidad - 1))} aria-label="Menos">−</button>
        <strong aria-live="polite">{cantidad}</strong>
        <button className="secundario" onClick={() => setCantidad(cantidad + 1)} aria-label="Más">+</button>
      </div>
      {comensales && comensales > 1 && (
        <label className="campo">
          <span>¿Para quién?</span>
          <select value={comensal ?? ""} onChange={(e) => setComensal(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Para la mesa</option>
            {Array.from({ length: comensales }, (_, i) => <option key={i} value={i + 1}>Persona {i + 1}</option>)}
          </select>
        </label>
      )}
      {plato.removibles.length > 0 && (
        <fieldset className="grupo">
          <legend>Quitar</legend>
          {plato.removibles.map((o) => (
            <label key={o.id} className="opcion">
              <input type="checkbox" checked={sin.includes(o.id)} onChange={() => alternar(sin, setSin, o.id)} />
              <span>Sin {o.nombre.toLowerCase()}</span>
            </label>
          ))}
        </fieldset>
      )}
      {plato.extras.length > 0 && (
        <fieldset className="grupo">
          <legend>Agregar</legend>
          {plato.extras.map((o) => (
            <label key={o.id} className="opcion">
              <input type="checkbox" checked={extras.includes(o.id)} onChange={() => alternar(extras, setExtras, o.id)} />
              <span>{o.nombre} <small>+{plata(o.precio)}</small></span>
            </label>
          ))}
        </fieldset>
      )}
      <label className="campo">
        <span>Nota para cocina</span>
        <input value={nota} maxLength={200} onChange={(e) => setNota(e.target.value)} placeholder="Ej: punto medio" />
      </label>
      <button disabled={ocupado} onClick={() => alAgregar({ cantidad, comensal, sin, extras, nota: nota.trim() })}>
        Anotar · {plata(total)}
      </button>
    </Dialogo>
  );
}

export function Dialogo({ titulo, alCerrar, children }: { titulo: string; alCerrar: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && alCerrar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [alCerrar]);
  return (
    <div className="velo" onClick={alCerrar}>
      <div className="dialogo" role="dialog" aria-modal="true" aria-label={titulo} onClick={(e) => e.stopPropagation()}>
        <div className="encabezado"><h2 style={{ margin: 0 }}>{titulo}</h2><button className="secundario" onClick={alCerrar} aria-label="Cerrar">✕</button></div>
        {children}
      </div>
    </div>
  );
}
