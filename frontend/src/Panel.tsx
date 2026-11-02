// ============================================================
// YEPAR RESTAURANT — frontend/src/Panel.tsx
// El panel del administrador: Inicio (asistente de arranque), Carga por Excel y Equipo (locales y personal).
// ============================================================
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { descargar, ErrorApi, pedir, type Sesion } from "./api";
import { Marca } from "./App";
import Configuracion from "./Configuracion";

type Pestana = "inicio" | "carga" | "equipo" | "config";
const PESTANAS: [Pestana, string][] = [["inicio", "Inicio"], ["carga", "Carga por Excel"], ["equipo", "Equipo"], ["config", "Configuración"]];

export default function Panel({ sesion, alSalir }: { sesion: Sesion; alSalir: () => void }) {
  const [pestana, setPestana] = useState<Pestana>("inicio");
  return (
    <div className="panel">
      <header className="barra">
        <Marca />
        <nav aria-label="Secciones">
          {PESTANAS.map(([id, texto]) => (
            <button key={id} className={"pestana" + (pestana === id ? " activa" : "")} onClick={() => setPestana(id)}>
              {texto}
            </button>
          ))}
        </nav>
        <div className="usuario">
          {sesion.codigo_acceso && <span className="chip" title="Código de acceso del restaurante">Código {sesion.codigo_acceso}</span>}
          <span>{sesion.usuario.nombre}</span>
          <button className="secundario" onClick={alSalir}>Salir</button>
        </div>
      </header>
      <main className="contenido">
        {pestana === "inicio" && <Inicio ir={setPestana} />}
        {pestana === "carga" && <Carga />}
        {pestana === "equipo" && <Equipo />}
        {pestana === "config" && <Configuracion sesion={sesion} />}
      </main>
    </div>
  );
}

// ── Inicio: el asistente de arranque ─────────────────────────
type Paso = { clave: string; titulo: string; hecho: boolean; detalle: string };
type Asistente = { pasos: Paso[]; completados: number; total: number; siguiente: string | null };

function Inicio({ ir }: { ir: (p: Pestana) => void }) {
  const [a, setA] = useState<Asistente | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    pedir<Asistente>("/carga-masiva/asistente").then(setA).catch((e) => setError(e.message));
  }, []);
  // A qué sección de esta web lleva cada paso (los que aún no tienen pantalla se hacen con la tablet o más adelante).
  const destino: Record<string, Pestana | undefined> = { insumos: "carga", platos: "carga", recetas: "carga", stock: "carga", personal: "equipo", sucursal: "equipo", mesas: "config", caja: "config", cobro: "config", facturacion: "config" };

  if (error) return <p className="error">{error}</p>;
  if (!a) return <p className="suave">Cargando…</p>;
  const pct = Math.round((a.completados / a.total) * 100);
  return (
    <section>
      <h1>Deja tu restaurante andando</h1>
      <p className="suave">
        {a.siguiente ? <>Siguiente paso: <strong>{a.siguiente}</strong></> : "¡Todo listo! Tu restaurante está configurado."}
      </p>
      <div className="progreso" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div style={{ width: `${pct}%` }} />
      </div>
      <p className="suave">{a.completados} de {a.total} pasos</p>
      <ol className="pasos">
        {a.pasos.map((p) => (
          <li key={p.clave} className={p.hecho ? "hecho" : ""}>
            <span className="marca-paso" aria-hidden="true">{p.hecho ? "✓" : ""}</span>
            <div>
              <strong>{p.titulo}</strong>
              <small>{p.detalle}</small>
            </div>
            {!p.hecho && destino[p.clave] && <button className="secundario" onClick={() => ir(destino[p.clave]!)}>Hacerlo</button>}
          </li>
        ))}
      </ol>
    </section>
  );
}

// ── Carga masiva por Excel ───────────────────────────────────
type ErrorFila = { hoja: string; fila: number; mensaje: string };
type Reporte = {
  valido: boolean; aplicado: boolean; insumos: number; platos: number; recetas: number;
  con_stock_inicial: number; categorias_nuevas: number; errores: ErrorFila[];
};

function Carga() {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [reporte, setReporte] = useState<Reporte | null>(null);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function enviar(accion: "validar" | "importar") {
    if (!archivo) return;
    setError("");
    setOcupado(true);
    const form = new FormData();
    form.append("archivo", archivo);
    try {
      setReporte(await pedir<Reporte>(`/carga-masiva/${accion}`, { form }));
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === 422 && (e.cuerpo as Reporte | undefined)?.errores) setReporte(e.cuerpo as Reporte);
      else setError((e as Error).message);
    } finally {
      setOcupado(false);
    }
  }

  return (
    <section>
      <h1>Carga por Excel</h1>
      <p className="suave">
        Carga tus ingredientes, tu carta y tus recetas de una sola vez. Primero descarga la planilla, llénala, y revísala antes de importar:
        si hay un error no se guarda nada.
      </p>
      <div className="acciones">
        <button className="secundario" onClick={() => descargar("/carga-masiva/plantilla", "plantilla_yepar_restaurant.xlsx").catch((e) => setError(e.message))}>
          1. Descargar la planilla
        </button>
        <label className="archivo">
          2. Elegir mi planilla
          <input type="file" accept=".xlsx" onChange={(e) => { setArchivo(e.target.files?.[0] ?? null); setReporte(null); }} />
        </label>
        {archivo && <span className="chip">{archivo.name}</span>}
      </div>
      <div className="acciones">
        <button className="secundario" disabled={!archivo || ocupado} onClick={() => enviar("validar")}>3. Revisar</button>
        <button disabled={!archivo || ocupado || reporte?.valido !== true || reporte?.aplicado === true} onClick={() => enviar("importar")}>4. Importar</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {reporte && <ResultadoCarga r={reporte} />}
    </section>
  );
}

function ResultadoCarga({ r }: { r: Reporte }) {
  return (
    <div className={"resultado " + (r.valido ? "ok" : "mal")} role="status">
      <strong>
        {r.aplicado ? "¡Importado!" : r.valido ? "La planilla está bien: ya puedes importarla." : `La planilla tiene ${r.errores.length} problema(s). No se guardó nada.`}
      </strong>
      <ul className="cifras">
        <li><b>{r.insumos}</b> insumos</li>
        <li><b>{r.platos}</b> platos</li>
        <li><b>{r.recetas}</b> recetas</li>
        <li><b>{r.con_stock_inicial}</b> con stock inicial</li>
        <li><b>{r.categorias_nuevas}</b> categorías nuevas</li>
      </ul>
      {r.errores.length > 0 && (
        <table>
          <thead><tr><th>Hoja</th><th>Fila</th><th>Qué corregir</th></tr></thead>
          <tbody>
            {r.errores.map((e, i) => (
              <tr key={i}><td>{e.hoja}</td><td>{e.fila}</td><td>{e.mensaje}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Equipo: locales y personal ───────────────────────────────
type Sucursal = { id: number; nombre: string };
type Persona = { id: number; nombre: string; username: string; roles: string[]; sucursal_id: number | null; estacion: string | null; activo: boolean };
const ROLES: Record<string, string> = { administrador: "Administrador", cajero: "Cajero", mesero: "Mesero", cocinero: "Cocinero" };

function Equipo() {
  const [locales, setLocales] = useState<Sucursal[]>([]);
  const [gente, setGente] = useState<Persona[]>([]);
  const [error, setError] = useState("");
  const cargar = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([pedir<Sucursal[]>("/sucursales"), pedir<Persona[]>("/personal")]);
      setLocales(s);
      setGente(p);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  const nombreLocal = (id: number | null) => locales.find((l) => l.id === id)?.nombre ?? "—";

  async function baja(p: Persona) {
    if (!confirm(`¿Dar de baja a ${p.nombre}? Ya no podrá entrar.`)) return;
    try {
      await pedir(`/personal/${p.id}`, { metodo: "PATCH", json: { activo: false } });
      cargar();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section>
      <h1>Equipo</h1>
      {error && <p className="error" role="alert">{error}</p>}
      <h2>Locales</h2>
      <ul className="lista">
        {locales.map((l) => <li key={l.id}>{l.nombre}</li>)}
      </ul>
      <NuevoLocal alCrear={cargar} />
      <h2>Personal</h2>
      <table>
        <thead><tr><th>Nombre</th><th>Usuario</th><th>Puesto</th><th>Local</th><th></th></tr></thead>
        <tbody>
          {gente.filter((p) => p.activo).map((p) => (
            <tr key={p.id}>
              <td>{p.nombre}</td>
              <td>{p.username}</td>
              <td>{p.roles.map((r) => ROLES[r] ?? r).join(", ")}{p.estacion ? ` (${p.estacion})` : ""}</td>
              <td>{nombreLocal(p.sucursal_id)}</td>
              <td><button className="enlace peligro" onClick={() => baja(p)}>Dar de baja</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <NuevaPersona locales={locales} alCrear={cargar} />
    </section>
  );
}

function NuevoLocal({ alCrear }: { alCrear: () => void }) {
  const [nombre, setNombre] = useState("");
  const [error, setError] = useState("");
  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await pedir("/sucursales", { json: { nombre } });
      setNombre("");
      alCrear();
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <form className="en-linea" onSubmit={enviar}>
      <input placeholder="Nombre del nuevo local" value={nombre} onChange={(e) => setNombre(e.target.value)} required aria-label="Nombre del nuevo local" />
      <button>Agregar local</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}

function NuevaPersona({ locales, alCrear }: { locales: Sucursal[]; alCrear: () => void }) {
  const vacio = { nombre: "", username: "", password: "", rol: "mesero", sucursal_id: "", estacion: "cocina" };
  const [f, setF] = useState(vacio);
  const [error, setError] = useState("");
  const [hecho, setHecho] = useState("");

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError("");
    setHecho("");
    try {
      await pedir("/personal", {
        json: {
          nombre: f.nombre, username: f.username, password: f.password, roles: [f.rol],
          sucursal_id: f.sucursal_id ? Number(f.sucursal_id) : (locales[0]?.id ?? null),
          estacion: f.rol === "cocinero" ? f.estacion : null,
        },
      });
      setHecho(`${f.nombre} ya puede entrar con su usuario y contraseña.`);
      setF(vacio);
      alCrear();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="formulario" onSubmit={enviar}>
      <h3>Agregar persona</h3>
      <div className="fila">
        <label className="campo"><span>Nombre</span><input value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} required /></label>
        <label className="campo"><span>Usuario</span><input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoCapitalize="off" required /></label>
        <label className="campo"><span>Contraseña</span><input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" required /></label>
      </div>
      <div className="fila">
        <label className="campo">
          <span>Puesto</span>
          <select value={f.rol} onChange={(e) => setF({ ...f, rol: e.target.value })}>
            {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {f.rol === "cocinero" && (
          <label className="campo">
            <span>Estación</span>
            <select value={f.estacion} onChange={(e) => setF({ ...f, estacion: e.target.value })}>
              <option value="cocina">Cocina</option>
              <option value="barra">Barra</option>
            </select>
          </label>
        )}
        <label className="campo">
          <span>Local</span>
          <select value={f.sucursal_id} onChange={(e) => setF({ ...f, sucursal_id: e.target.value })}>
            {locales.map((l) => <option key={l.id} value={l.id}>{l.nombre}</option>)}
          </select>
        </label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {hecho && <p className="exito" role="status">{hecho}</p>}
      <button>Agregar persona</button>
    </form>
  );
}
