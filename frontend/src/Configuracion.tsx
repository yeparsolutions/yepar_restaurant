// ============================================================
// YEPAR RESTAURANT — frontend/src/Configuracion.tsx
// Lo que falta para abrir el local: plano de mesas, cajas y terminales, propina y facturador.
// Cada bloque es independiente: guarda al instante y avisa si algo falla.
// ============================================================
import { useCallback, useEffect, useRef, useState, type FormEvent, type PointerEvent } from "react";
import { ErrorApi, pedir, type Sesion } from "./api";

type Sucursal = { id: number; nombre: string };

export default function Configuracion({ sesion }: { sesion: Sesion }) {
  const [locales, setLocales] = useState<Sucursal[]>([]);
  const [local, setLocal] = useState<number | null>(sesion.usuario.sucursal_id);
  const [error, setError] = useState("");

  useEffect(() => {
    pedir<Sucursal[]>("/sucursales")
      .then((l) => {
        setLocales(l);
        setLocal((actual) => actual ?? l[0]?.id ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);

  return (
    <section>
      <h1>Configuración</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {locales.length > 1 && (
        <label className="campo" style={{ maxWidth: 320 }}>
          <span>Local</span>
          <select value={local ?? ""} onChange={(e) => setLocal(Number(e.target.value))}>
            {locales.map((l) => <option key={l.id} value={l.id}>{l.nombre}</option>)}
          </select>
        </label>
      )}
      {local !== null && <Mesas key={`m${local}`} local={local} />}
      {local !== null && <Cajas key={`c${local}`} local={local} />}
      <Propina />
      <Facturador />
    </section>
  );
}

// ── Mesas: plano que se arrastra ─────────────────────────────
type Mesa = { mesa_id: number; nombre: string; capacidad: number; pos_x: number; pos_y: number; ancho: number; alto: number; forma: string };
const TAMANO: Record<string, [number, number]> = { cuadrada: [80, 80], redonda: [80, 80], rectangular: [130, 70] };

function Mesas({ local }: { local: number }) {
  const [mesas, setMesas] = useState<Mesa[]>([]);
  const [error, setError] = useState("");
  const cargar = useCallback(async () => {
    try {
      setMesas(await pedir<Mesa[]>(`/mesas?sucursal_id=${local}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [local]);
  useEffect(() => { cargar(); }, [cargar]);

  // Dónde cae la próxima mesa: una cuadrícula ordenada, para que no se encimen.
  const hueco = (i: number) => ({ pos_x: 10 + (i % 6) * 110, pos_y: 10 + Math.floor(i / 6) * 100 });

  async function crear(nombre: string, capacidad: number, forma: string, indice: number) {
    const [ancho, alto] = TAMANO[forma] ?? TAMANO.cuadrada;
    await pedir("/mesas", { json: { nombre, capacidad, forma, ancho, alto, sucursal_id: local, ...hueco(indice) } });
  }

  return (
    <div className="bloque">
      <h2>Mesas del salón</h2>
      <p className="suave">Arrastra cada mesa para dejarla donde está en tu local. Los meseros verán este mismo plano.</p>
      {error && <p className="error" role="alert">{error}</p>}
      <Plano mesas={mesas} alMover={cargar} alFallar={setError} />
      <NuevasMesas existentes={mesas} crear={crear} alTerminar={cargar} alFallar={setError} />
    </div>
  );
}

function Plano({ mesas, alMover, alFallar }: { mesas: Mesa[]; alMover: () => void; alFallar: (m: string) => void }) {
  const [arrastre, setArrastre] = useState<{ id: number; dx: number; dy: number; x: number; y: number } | null>(null);
  const lienzo = useRef<HTMLDivElement>(null);

  function empezar(e: PointerEvent<HTMLDivElement>, m: Mesa) {
    e.currentTarget.setPointerCapture(e.pointerId);
    const caja = lienzo.current!.getBoundingClientRect();
    setArrastre({ id: m.mesa_id, dx: e.clientX - caja.left - m.pos_x, dy: e.clientY - caja.top - m.pos_y, x: m.pos_x, y: m.pos_y });
  }
  function mover(e: PointerEvent<HTMLDivElement>) {
    if (!arrastre) return;
    const caja = lienzo.current!.getBoundingClientRect();
    setArrastre({ ...arrastre, x: Math.max(0, Math.round(e.clientX - caja.left - arrastre.dx)), y: Math.max(0, Math.round(e.clientY - caja.top - arrastre.dy)) });
  }
  async function soltar() {
    if (!arrastre) return;
    const a = arrastre;
    setArrastre(null);
    try {
      await pedir(`/mesas/${a.id}/posicion`, { metodo: "PATCH", json: { pos_x: a.x, pos_y: a.y } });
      alMover();
    } catch (e) {
      alFallar((e as Error).message);
    }
  }

  const ancho = Math.max(680, ...mesas.map((m) => m.pos_x + m.ancho + 20));
  const alto = Math.max(300, ...mesas.map((m) => m.pos_y + m.alto + 20));
  return (
    <div className="plano-marco">
      <div ref={lienzo} className="plano" style={{ width: ancho, height: alto }}>
        {mesas.length === 0 && <p className="suave vacio">Aún no hay mesas. Agrégalas abajo.</p>}
        {mesas.map((m) => {
          const arr = arrastre?.id === m.mesa_id ? arrastre : null;
          return (
            <div
              key={m.mesa_id}
              className={"mesa " + m.forma + (arr ? " moviendo" : "")}
              style={{ left: arr?.x ?? m.pos_x, top: arr?.y ?? m.pos_y, width: m.ancho, height: m.alto }}
              onPointerDown={(e) => empezar(e, m)}
              onPointerMove={mover}
              onPointerUp={soltar}
              onPointerCancel={() => setArrastre(null)}
              role="button"
              aria-label={`${m.nombre}, ${m.capacidad} personas. Arrastra para mover.`}
            >
              <strong>{m.nombre}</strong>
              <small>{m.capacidad} pers.</small>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function NuevasMesas(p: { existentes: Mesa[]; crear: (n: string, c: number, f: string, i: number) => Promise<void>; alTerminar: () => void; alFallar: (m: string) => void }) {
  const [nombre, setNombre] = useState("");
  const [capacidad, setCapacidad] = useState(4);
  const [forma, setForma] = useState("cuadrada");
  const [cuantas, setCuantas] = useState(10);
  const [ocupado, setOcupado] = useState(false);

  async function una(e: FormEvent) {
    e.preventDefault();
    p.alFallar("");
    setOcupado(true);
    try {
      await p.crear(nombre, capacidad, forma, p.existentes.length);
      setNombre("");
      p.alTerminar();
    } catch (err) {
      p.alFallar((err as Error).message);
    } finally {
      setOcupado(false);
    }
  }

  async function varias() {
    p.alFallar("");
    setOcupado(true);
    // Sigue la numeración: si ya existen "Mesa 1" a "Mesa 4", la próxima es "Mesa 5".
    const usados = p.existentes.map((m) => Number(/^Mesa (\d+)$/.exec(m.nombre)?.[1] ?? 0));
    let n = Math.max(0, ...usados);
    try {
      for (let i = 0; i < cuantas; i++) await p.crear(`Mesa ${++n}`, capacidad, forma, p.existentes.length + i);
    } catch (err) {
      p.alFallar((err as Error).message);
    } finally {
      p.alTerminar();
      setOcupado(false);
    }
  }

  return (
    <div className="formulario">
      <h3>Agregar mesas</h3>
      <form className="fila" onSubmit={una}>
        <label className="campo"><span>Nombre</span><input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Terraza 1" required /></label>
        <label className="campo"><span>Personas</span><input type="number" min={1} max={30} value={capacidad} onChange={(e) => setCapacidad(Number(e.target.value))} /></label>
        <label className="campo">
          <span>Forma</span>
          <select value={forma} onChange={(e) => setForma(e.target.value)}>
            <option value="cuadrada">Cuadrada</option>
            <option value="redonda">Redonda</option>
            <option value="rectangular">Rectangular</option>
          </select>
        </label>
        <div className="campo"><span>&nbsp;</span><button disabled={ocupado}>Agregar mesa</button></div>
      </form>
      <div className="en-linea">
        <span>O crea de una vez</span>
        <input type="number" min={1} max={40} value={cuantas} onChange={(e) => setCuantas(Number(e.target.value))} aria-label="Cantidad de mesas" style={{ maxWidth: 90, flex: "none" }} />
        <span>mesas numeradas («Mesa 1», «Mesa 2»…) con la forma y personas de arriba</span>
        <button className="secundario" type="button" disabled={ocupado || cuantas < 1} onClick={varias}>Crear {cuantas} mesas</button>
      </div>
    </div>
  );
}

// ── Cajas y terminales de tarjeta ────────────────────────────
type Simple = { id: number; nombre: string };

function Cajas({ local }: { local: number }) {
  return (
    <div className="bloque">
      <h2>Caja y terminales</h2>
      <p className="suave">La caja es donde el cajero abre su turno y cobra. Los terminales son los aparatos de tarjeta (uno por mesero o por zona).</p>
      <div className="dos">
        <ListaSimple titulo="Cajas" ruta="/cajas" local={local} ejemplo="Caja principal" boton="Agregar caja" />
        <ListaSimple titulo="Terminales de tarjeta" ruta="/terminales" local={local} ejemplo="Terminal 1" boton="Agregar terminal" />
      </div>
    </div>
  );
}

function ListaSimple(p: { titulo: string; ruta: string; local: number; ejemplo: string; boton: string }) {
  const [filas, setFilas] = useState<Simple[]>([]);
  const [nombre, setNombre] = useState("");
  const [error, setError] = useState("");
  const cargar = useCallback(() => {
    pedir<Simple[]>(`${p.ruta}?sucursal_id=${p.local}`).then(setFilas).catch((e) => setError(e.message));
  }, [p.ruta, p.local]);
  useEffect(() => { cargar(); }, [cargar]);

  async function agregar(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await pedir(p.ruta, { json: { nombre, sucursal_id: p.local } });
      setNombre("");
      cargar();
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <div>
      <h3>{p.titulo}</h3>
      <ul className="lista">
        {filas.length === 0 && <li className="suave">Ninguna todavía.</li>}
        {filas.map((f) => <li key={f.id}>{f.nombre}</li>)}
      </ul>
      <form className="en-linea" onSubmit={agregar}>
        <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder={p.ejemplo} required aria-label={p.boton} />
        <button>{p.boton}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}

// ── Propina ──────────────────────────────────────────────────
type ConfigCobro = { propina_modo: "por_mesa" | "grupal"; propina_sugerida_pct: string };

function Propina() {
  const [modo, setModo] = useState<"por_mesa" | "grupal">("por_mesa");
  const [pct, setPct] = useState("10");
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null);
  useEffect(() => {
    pedir<ConfigCobro>("/configuracion/cobro")
      .then((c) => { setModo(c.propina_modo); setPct(String(Number(c.propina_sugerida_pct))); })
      .catch((e) => setMsg({ ok: false, texto: e.message }));
  }, []);

  async function guardar(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      await pedir("/configuracion/cobro", { metodo: "PUT", json: { propina_modo: modo, propina_sugerida_pct: pct } });
      setMsg({ ok: true, texto: "Propina guardada." });
    } catch (err) {
      setMsg({ ok: false, texto: (err as Error).message });
    }
  }
  return (
    <div className="bloque">
      <h2>Propina</h2>
      <form className="formulario" onSubmit={guardar}>
        <fieldset>
          <legend>¿Cómo se reparte?</legend>
          <label className="opcion"><input type="radio" name="modo" checked={modo === "por_mesa"} onChange={() => setModo("por_mesa")} />
            <span><strong>Por mesa</strong><small>La propina de cada mesa es de su mesero.</small></span></label>
          <label className="opcion"><input type="radio" name="modo" checked={modo === "grupal"} onChange={() => setModo("grupal")} />
            <span><strong>Grupal</strong><small>Todo va a un fondo común que se reparte entre el equipo.</small></span></label>
        </fieldset>
        <label className="campo" style={{ maxWidth: 220 }}>
          <span>Propina sugerida (%)</span>
          <input type="number" min={0} max={30} step={0.5} value={pct} onChange={(e) => setPct(e.target.value)} required />
        </label>
        {msg && <p className={msg.ok ? "exito" : "error"} role="status">{msg.texto}</p>}
        <button>Guardar propina</button>
      </form>
    </div>
  );
}

// ── Facturador ───────────────────────────────────────────────
type Conexion = { proveedor: string; activo: boolean; api_key_final: string; emision_automatica: boolean; tipo_automatico: string };
const NOMBRE_PROVEEDOR: Record<string, string> = { yepardte: "YeparDTE (Chile)", yeparfactura: "YeparFactura (Venezuela)" };

function Facturador() {
  const [con, setCon] = useState<Conexion | null>(null);
  const [cargado, setCargado] = useState(false);
  const [proveedor, setProveedor] = useState("yepardte");
  const [clave, setClave] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(async () => {
    try {
      setCon(await pedir<Conexion>("/facturacion/conexion"));
    } catch (e) {
      // Sin facturador la API responde 422 ("no tiene un facturador conectado"): es un estado normal, no un fallo.
      if (e instanceof ErrorApi && e.estado === 422) setCon(null);
      else setMsg({ ok: false, texto: (e as Error).message });
    } finally {
      setCargado(true);
    }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);

  async function conectar(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    setOcupado(true);
    try {
      setCon(await pedir<Conexion>("/facturacion/conexion", { metodo: "PUT", json: { proveedor, api_key: clave } }));
      setClave("");
      setMsg({ ok: true, texto: "Facturador conectado." });
    } catch (err) {
      setMsg({ ok: false, texto: (err as Error).message });
    } finally {
      setOcupado(false);
    }
  }
  async function desconectar() {
    if (!confirm("¿Desconectar el facturador? No se podrán emitir boletas ni facturas hasta volver a conectarlo.")) return;
    try {
      await pedir("/facturacion/conexion", { metodo: "DELETE" });
      setCon(null);
      setMsg(null);
    } catch (err) {
      setMsg({ ok: false, texto: (err as Error).message });
    }
  }
  async function automatica(valor: boolean) {
    try {
      setCon(await pedir<Conexion>("/facturacion/configuracion", { metodo: "PUT", json: { emision_automatica: valor } }));
    } catch (err) {
      setMsg({ ok: false, texto: (err as Error).message });
    }
  }

  return (
    <div className="bloque">
      <h2>Facturador</h2>
      <p className="suave">Para emitir boletas y facturas, conecta tu cuenta de YeparDTE (Chile) o YeparFactura (Venezuela) con su API Key. Se guarda cifrada.</p>
      {!cargado ? <p className="suave">Cargando…</p> : con && con.activo ? (
        <div className="formulario">
          <p><span className="chip">Conectado</span> <strong>{NOMBRE_PROVEEDOR[con.proveedor] ?? con.proveedor}</strong> · clave {con.api_key_final}</p>
          {con.proveedor === "yepardte" && (
            <label className="opcion">
              <input type="checkbox" checked={con.emision_automatica} onChange={(e) => automatica(e.target.checked)} />
              <span><strong>Emitir la boleta sola al cerrar la mesa</strong><small>Si lo apagas, el cajero la emite a mano.</small></span>
            </label>
          )}
          <button className="secundario" onClick={desconectar}>Desconectar</button>
          {msg && <p className={msg.ok ? "exito" : "error"} role="status">{msg.texto}</p>}
        </div>
      ) : (
        <form className="formulario" onSubmit={conectar}>
          <div className="fila">
            <label className="campo">
              <span>Facturador</span>
              <select value={proveedor} onChange={(e) => setProveedor(e.target.value)}>
                <option value="yepardte">YeparDTE (Chile)</option>
                <option value="yeparfactura">YeparFactura (Venezuela)</option>
              </select>
            </label>
            <label className="campo" style={{ flex: 2 }}>
              <span>API Key</span>
              <input type="password" value={clave} onChange={(e) => setClave(e.target.value)} autoComplete="off" minLength={8} required />
            </label>
          </div>
          {msg && <p className={msg.ok ? "exito" : "error"} role="alert">{msg.texto}</p>}
          <button disabled={ocupado}>{ocupado ? "Probando la clave…" : "Conectar"}</button>
        </form>
      )}
    </div>
  );
}
