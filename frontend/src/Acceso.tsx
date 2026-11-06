// ============================================================
// YEPAR RESTAURANT — frontend/src/Acceso.tsx
// La puerta de entrada, sin código de restaurante:
//   · Administrador: correo + contraseña (o crear su restaurante).
//   · Tablet vinculada: el personal toca su nombre y escribe su contraseña.
// La tablet se vincula UNA vez abriendo el enlace que genera el administrador (Equipo → Tablets).
// ============================================================
import { useEffect, useState, type FormEvent } from "react";
import { guardarVinculo, pedir, type Sesion } from "./api";
import { Marca } from "./App";

type Props = { alIniciar: (s: Sesion) => void; vinculo: string | null; aviso: string; alDesvincular: () => void };

export default function Acceso({ alIniciar, vinculo, aviso, alDesvincular }: Props) {
  // Una tablet vinculada abre directo en la pantalla del equipo; el administrador entra por el enlace de abajo.
  const [comoAdmin, setComoAdmin] = useState(!vinculo);
  // El enlace puede validarse DESPUÉS de montar esta pantalla (al abrir #/vincular/…): cuando llega, pasa a la del equipo.
  useEffect(() => setComoAdmin(!vinculo), [vinculo]);
  if (vinculo && !comoAdmin) {
    return <Equipo alIniciar={alIniciar} vinculo={vinculo} aviso={aviso} alAdmin={() => setComoAdmin(true)} alDesvincular={alDesvincular} />;
  }
  return <Admin alIniciar={alIniciar} aviso={aviso} alEquipo={vinculo ? () => setComoAdmin(false) : null} />;
}

function Campo(props: { etiqueta: string; valor: string; cambiar: (v: string) => void; tipo?: string; ayuda?: string; auto?: string }) {
  return (
    <label className="campo">
      <span>{props.etiqueta}</span>
      <input type={props.tipo ?? "text"} value={props.valor} autoComplete={props.auto} autoCapitalize="off" onChange={(e) => props.cambiar(e.target.value)} required />
      {props.ayuda && <small>{props.ayuda}</small>}
    </label>
  );
}

// ── Administrador ────────────────────────────────────────────
function Admin({ alIniciar, aviso, alEquipo }: { alIniciar: (s: Sesion) => void; aviso: string; alEquipo: (() => void) | null }) {
  const [modo, setModo] = useState<"entrar" | "crear">("entrar");
  const [registroAbierto, setRegistroAbierto] = useState(true);
  const [nueva, setNueva] = useState<Sesion | null>(null);

  useEffect(() => {
    pedir<{ abierto: boolean }>("/registro/estado", { token: "" }).then((r) => setRegistroAbierto(r.abierto)).catch(() => {});
  }, []);

  if (nueva) return <Listo sesion={nueva} continuar={() => alIniciar(nueva)} />;
  return (
    <main className="centro">
      <div className="tarjeta">
        <Marca />
        {aviso && <p className="exito" role="status">{aviso}</p>}
        {modo === "entrar" ? <Entrar alIniciar={alIniciar} /> : <Crear alCrear={setNueva} />}
        {registroAbierto && (
          <p className="cambio">
            {modo === "entrar" ? "¿Primera vez aquí?" : "¿Ya tienes restaurante?"}{" "}
            <button className="enlace" onClick={() => setModo(modo === "entrar" ? "crear" : "entrar")}>
              {modo === "entrar" ? "Crear mi restaurante" : "Iniciar sesión"}
            </button>
          </p>
        )}
        {alEquipo && <p className="cambio"><button className="enlace" onClick={alEquipo}>Volver a la pantalla del equipo</button></p>}
      </div>
    </main>
  );
}

function Entrar({ alIniciar }: { alIniciar: (s: Sesion) => void }) {
  const [correo, setCorreo] = useState("");
  const [codigo, setCodigo] = useState("");
  const [usuario, setUsuario] = useState("");
  const [clave, setClave] = useState("");
  const [anterior, setAnterior] = useState(false); // cuentas creadas antes de que existiera el correo
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError("");
    setCargando(true);
    try {
      const json = anterior ? { codigo_empresa: codigo, username: usuario, password: clave } : { email: correo, password: clave };
      alIniciar(await pedir<Sesion>("/auth/login", { json, token: "" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCargando(false);
    }
  }
  return (
    <form onSubmit={enviar}>
      <h1>Iniciar sesión</h1>
      {anterior ? (
        <>
          <p className="suave">Para cuentas creadas antes de usar correo. Al entrar, el panel te pedirá registrar tu correo.</p>
          <Campo etiqueta="Código del restaurante" valor={codigo} cambiar={(v) => setCodigo(v.toUpperCase())} ayuda="Son 8 letras y números." />
          <Campo etiqueta="Usuario" valor={usuario} cambiar={setUsuario} auto="username" />
        </>
      ) : (
        <Campo etiqueta="Correo" valor={correo} cambiar={setCorreo} tipo="email" auto="email" />
      )}
      <Campo etiqueta="Contraseña" valor={clave} cambiar={setClave} tipo="password" auto="current-password" />
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={cargando}>{cargando ? "Entrando…" : "Entrar"}</button>
      <p className="cambio">
        <button type="button" className="enlace" onClick={() => { setAnterior(!anterior); setError(""); }}>
          {anterior ? "Entrar con mi correo" : "Mi cuenta es anterior (con código)"}
        </button>
      </p>
    </form>
  );
}

function Crear({ alCrear }: { alCrear: (s: Sesion) => void }) {
  const [f, setF] = useState({ restaurante: "", sucursal: "Casa matriz", nombre: "", correo: "", clave: "", pais: "CL", moneda: "CLP" });
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);
  const poner = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError("");
    setCargando(true);
    try {
      alCrear(
        await pedir<Sesion>("/registro", {
          token: "",
          json: { nombre_restaurante: f.restaurante, sucursal: f.sucursal, admin_nombre: f.nombre, email: f.correo, password: f.clave, pais: f.pais, moneda: f.moneda },
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCargando(false);
    }
  }
  return (
    <form onSubmit={enviar}>
      <h1>Crear mi restaurante</h1>
      <Campo etiqueta="Nombre del restaurante" valor={f.restaurante} cambiar={poner("restaurante")} />
      <Campo etiqueta="Nombre de tu primer local" valor={f.sucursal} cambiar={poner("sucursal")} />
      <Campo etiqueta="Tu nombre" valor={f.nombre} cambiar={poner("nombre")} auto="name" />
      <Campo etiqueta="Tu correo" valor={f.correo} cambiar={poner("correo")} tipo="email" auto="email" ayuda="Con él iniciarás sesión." />
      <Campo etiqueta="Contraseña" valor={f.clave} cambiar={poner("clave")} tipo="password" auto="new-password" ayuda="Mínimo 8 caracteres." />
      <div className="fila">
        <label className="campo">
          <span>País</span>
          <select value={f.pais} onChange={(e) => setF({ ...f, pais: e.target.value, moneda: e.target.value === "VE" ? "VES" : "CLP" })}>
            <option value="CL">Chile</option>
            <option value="VE">Venezuela</option>
          </select>
        </label>
        <label className="campo">
          <span>Moneda</span>
          <select value={f.moneda} onChange={(e) => poner("moneda")(e.target.value)}>
            <option value="CLP">Peso chileno (CLP)</option>
            <option value="VES">Bolívar (VES)</option>
            <option value="USD">Dólar (USD)</option>
          </select>
        </label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={cargando}>{cargando ? "Creando…" : "Crear restaurante"}</button>
    </form>
  );
}

function Listo({ sesion, continuar }: { sesion: Sesion; continuar: () => void }) {
  return (
    <main className="centro">
      <div className="tarjeta">
        <Marca />
        <h1>¡Tu restaurante está listo!</h1>
        <p className="suave">
          Entra a tu panel y carga tu carta. Cuando quieras usar tablets en el salón o la cocina, ve a <strong>Equipo → Tablets</strong> y
          genera un enlace: lo abres una sola vez en cada tablet y tu equipo entra tocando su nombre, sin códigos.
        </p>
        <p className="suave">Tu cuenta: <strong>{sesion.usuario.email}</strong></p>
        <button onClick={continuar}>Ir a mi panel</button>
      </div>
    </main>
  );
}

// ── Tablet vinculada: el personal toca su nombre ─────────────
type Persona = { nombre: string; username: string; roles: string[]; estacion: string | null };
type Tablet = { restaurante: string; personal: Persona[] };
const PUESTO: Record<string, string> = { cajero: "Caja", mesero: "Mesero", cocinero: "Cocina" };

function Equipo(p: { alIniciar: (s: Sesion) => void; vinculo: string; aviso: string; alAdmin: () => void; alDesvincular: () => void }) {
  const [tablet, setTablet] = useState<Tablet | null>(null);
  const [error, setError] = useState("");
  const [elegida, setElegida] = useState<Persona | null>(null);
  const [clave, setClave] = useState("");
  const [cargando, setCargando] = useState(false);

  useEffect(() => {
    pedir<Tablet>(`/acceso/vinculo/${p.vinculo}`, { token: "" })
      .then(setTablet)
      .catch((e) => {
        // El enlace ya no vale (el administrador desvinculó las tablets): esta tablet debe vincularse de nuevo.
        setError(e.message);
        guardarVinculo(null);
      });
  }, [p.vinculo]);

  async function entrar(e: FormEvent) {
    e.preventDefault();
    if (!elegida) return;
    setError("");
    setCargando(true);
    try {
      p.alIniciar(await pedir<Sesion>("/auth/login", { json: { vinculo: p.vinculo, username: elegida.username, password: clave }, token: "" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCargando(false);
    }
  }

  if (error && !tablet) {
    return (
      <main className="centro">
        <div className="tarjeta">
          <Marca />
          <h1>Esta tablet ya no está vinculada</h1>
          <p className="error" role="alert">{error}</p>
          <button onClick={p.alAdmin}>Entrar como administrador</button>
        </div>
      </main>
    );
  }
  if (!tablet) return <main className="centro"><p className="suave">Cargando…</p></main>;

  return (
    <main className="centro">
      <div className="tarjeta ancha">
        <Marca />
        {p.aviso && <p className="exito" role="status">{p.aviso}</p>}
        <h1>{tablet.restaurante}</h1>
        {!elegida ? (
          <>
            <p className="suave">¿Quién eres?</p>
            {tablet.personal.length === 0 ? <p className="suave">Aún no hay personal. El administrador lo crea en Equipo.</p> : (
              <div className="nombres">
                {tablet.personal.map((x) => (
                  <button key={x.username} className="nombre" onClick={() => { setElegida(x); setClave(""); setError(""); }}>
                    <strong>{x.nombre}</strong>
                    <small>{x.roles.map((r) => PUESTO[r] ?? r).join(", ")}{x.estacion ? ` · ${x.estacion}` : ""}</small>
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          <form onSubmit={entrar}>
            <p className="suave">Hola, <strong>{elegida.nombre}</strong>. Escribe tu contraseña.</p>
            <label className="campo">
              <span>Contraseña</span>
              <input type="password" value={clave} onChange={(e) => setClave(e.target.value)} autoComplete="current-password" autoFocus required />
            </label>
            {error && <p className="error" role="alert">{error}</p>}
            <button disabled={cargando}>{cargando ? "Entrando…" : "Entrar"}</button>
            <p className="cambio"><button type="button" className="enlace" onClick={() => { setElegida(null); setError(""); }}>No soy yo</button></p>
          </form>
        )}
        <p className="cambio"><button className="enlace" onClick={p.alAdmin}>Soy administrador</button></p>
      </div>
    </main>
  );
}
