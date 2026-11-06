// ============================================================
// YEPAR RESTAURANT — frontend/src/Mesero.tsx
// La pantalla del mesero en la tablet: plano de mesas → pedido de la mesa → carta → enviar a cocina.
// Analogía: es la libreta del mesero. Cada plato se anota en la libreta (estado "tomada") y solo
// cuando toca "Enviar a cocina" las hojas viajan a la cocina; antes de eso se pueden tachar sin costo.
// ============================================================
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pedir, type Sesion } from "./api";
import { Marca } from "./App";

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
  id: string; item_id: number; nombre: string; cantidad: number; precio_unitario: string; comensal: number | null;
  nota: string | null; estado: string; estacion: string; quitados: number[]; extras: number[]; total: string;
};
type Cuenta = { subtotal: string; descuento: string; propina: string; total: string; pagado: string; pendiente: string };
type Pedido = { id: string; mesa: string | null; estado: string; comensales: number | null; lineas: Linea[]; cuenta: Cuenta };

const ETIQUETA_ESTADO: Record<string, string> = {
  tomada: "En la libreta", enviada: "En cocina", en_preparacion: "Preparando", lista: "¡Lista!", entregada: "Entregada", cancelada: "Cancelada",
};
const ESTADOS_MESA: Record<EstadoMesa, string> = { libre: "Libre", ocupada: "Ocupada", lista: "Plato listo", cuenta_pedida: "Pidió la cuenta" };

const plata = (v: string | number | null | undefined) => {
  const n = Number(v ?? 0);
  return "$" + n.toLocaleString("es-CL", { maximumFractionDigits: 2 });
};
const nuevoId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
// La API entrega ids de lo quitado/agregado; los nombres salen de la carta.
const nombresDe = (ids: number[], opciones: Opcion[]) => ids.map((i) => opciones.find((o) => o.id === i)?.nombre ?? "…").join(", ");

export default function Mesero({ sesion, alSalir }: { sesion: Sesion; alSalir: () => void }) {
  const [pedidoId, setPedidoId] = useState<string | null>(null);
  return (
    <>
      <header className="barra">
        <Marca />
        <span className="suave">Mesero · {sesion.usuario.nombre}</span>
        <span style={{ flex: 1 }} />
        <button className="secundario" onClick={alSalir}>Salir</button>
      </header>
      <main className="contenido">
        {pedidoId ? <VistaPedido pedidoId={pedidoId} alVolver={() => setPedidoId(null)} /> : <Plano alAbrir={setPedidoId} />}
      </main>
    </>
  );
}

// ── Plano de mesas ──────────────────────────────────────────
function Plano({ alAbrir }: { alAbrir: (pedidoId: string) => void }) {
  const [mesas, setMesas] = useState<Mesa[] | null>(null);
  const [error, setError] = useState("");
  const [comensales, setComensales] = useState<Mesa | null>(null);
  const listasAntes = useRef<Set<number>>(new Set());

  const cargar = useCallback(async () => {
    try {
      const m = await pedir<Mesa[]>("/mesas");
      // Avisa con vibración cuando una mesa pasa a "lista" (la cocina terminó un plato).
      const ahora = new Set(m.filter((x) => x.estado === "lista").map((x) => x.mesa_id));
      if ([...ahora].some((id) => !listasAntes.current.has(id))) navigator.vibrate?.([200, 100, 200]);
      listasAntes.current = ahora;
      setMesas(m);
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    cargar();
    const t = setInterval(cargar, 8000);
    return () => clearInterval(t);
  }, [cargar]);

  const abrir = async (mesa: Mesa, n: number | null) => {
    try {
      const p = await pedir<Pedido>("/pedidos", { json: { mesa_id: mesa.mesa_id, comensales: n, pedido_id: nuevoId() } });
      alAbrir(p.id);
    } catch (e: any) {
      setError(e.message);
      setComensales(null);
      cargar();
    }
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
  const [pedido, setPedido] = useState<Pedido | null>(null);
  const [carta, setCarta] = useState<Plato[]>([]);
  const [categoria, setCategoria] = useState("Todo");
  const [busca, setBusca] = useState("");
  const [elegido, setElegido] = useState<Plato | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const recargar = useCallback(async () => {
    try {
      setPedido(await pedir<Pedido>(`/pedidos/${pedidoId}`));
    } catch (e: any) {
      setError(e.message);
    }
  }, [pedidoId]);
  useEffect(() => {
    recargar();
    pedir<Plato[]>("/carta").then(setCarta).catch((e) => setError(e.message));
    const t = setInterval(recargar, 8000);
    return () => clearInterval(t);
  }, [recargar]);

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

  const agregar = (datos: { cantidad: number; comensal: number | null; sin: number[]; extras: number[]; nota: string }, plato: Plato) =>
    hacer(async () => {
      const r = await pedir<{ disponibilidad: { alcanza: boolean; faltas: Falta[] } }>(`/pedidos/${pedidoId}/lineas`, {
        json: {
          item_id: plato.item_id, cantidad: datos.cantidad, comensal: datos.comensal, sin_ingredientes: datos.sin,
          extra_ids: datos.extras, nota: datos.nota || null, linea_id: nuevoId(),
        },
      });
      setElegido(null);
      if (!r.disponibilidad.alcanza) setAviso(`Ojo: a ${plato.nombre} le falta ${r.disponibilidad.faltas.map((f) => f.nombre).join(", ")}. Igual quedó anotado.`);
      else setAviso(`${plato.nombre} anotado.`);
    });

  const enviar = () =>
    hacer(async () => {
      const r = await pedir<{ lineas: unknown[]; faltantes: { nombre: string }[] }>(`/pedidos/${pedidoId}/enviar`, { metodo: "POST" });
      setAviso(
        r.faltantes?.length
          ? `Enviado. Avisa a cocina: falta ${r.faltantes.map((f) => f.nombre).join(", ")}.`
          : `Enviado a cocina (${r.lineas.length} plato${r.lineas.length === 1 ? "" : "s"}).`,
      );
    });

  const pedirCuenta = () => hacer(() => pedir(`/pedidos/${pedidoId}/cuenta`, { metodo: "POST" }), "Cuenta pedida. La caja la recibirá.");
  const borrar = (l: Linea) => hacer(() => pedir(`/lineas/${l.id}`, { metodo: "DELETE" }));
  const cancelar = (l: Linea) => {
    if (window.confirm(`¿Cancelar "${l.nombre}"? Si cocina ya lo preparó, quedará como merma.`))
      hacer(() => pedir(`/lineas/${l.id}/cancelar`, { metodo: "POST" }), `${l.nombre} cancelado.`);
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
                <span className={`estado ${l.estado}`}>{ETIQUETA_ESTADO[l.estado] ?? l.estado}</span>
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
        ) : (
          <p className="suave">Esta cuenta está en estado «{pedido.estado}».</p>
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

      {elegido && (
        <DialogoPlato plato={elegido} comensales={pedido.comensales} ocupado={ocupado} alCerrar={() => setElegido(null)} alAgregar={(d) => agregar(d, elegido)} />
      )}
    </div>
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
