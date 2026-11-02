// ============================================================
// YEPAR RESTAURANT — frontend/src/Acceso.tsx
// La puerta de entrada: iniciar sesión con el código del restaurante, o crear un restaurante nuevo.
// Al crear uno, se muestra el CÓDIGO DE ACCESO (con él entra todo el equipo) antes de pasar al panel.
// ============================================================
import { useEffect, useState, type FormEvent } from "react";
import { pedir, type Sesion } from "./api";
import { Marca } from "./App";

type Modo = "entrar" | "crear";

export default function Acceso({ alIniciar }: { alIniciar: (s: Sesion) => void }) {
  const [modo, setModo] = useState<Modo>("entrar");
  const [registroAbierto, setRegistroAbierto] = useState(true);
  const [nueva, setNueva] = useState<Sesion | null>(null);

  useEffect(() => {
    pedir<{ abierto: boolean }>("/registro/estado").then((r) => setRegistroAbierto(r.abierto)).catch(() => {});
  }, []);

  if (nueva) return <CodigoNuevo sesion={nueva} continuar={() => alIniciar(nueva)} />;

  return (
    <main className="centro">
      <div className="tarjeta">
        <Marca />
        {modo === "entrar" ? <Entrar alIniciar={alIniciar} /> : <Crear alCrear={setNueva} />}
        {registroAbierto && (
          <p className="cambio">
            {modo === "entrar" ? "¿Primera vez aquí?" : "¿Ya tienes restaurante?"}{" "}
            <button className="enlace" onClick={() => setModo(modo === "entrar" ? "crear" : "entrar")}>
              {modo === "entrar" ? "Crear mi restaurante" : "Iniciar sesión"}
            </button>
          </p>
        )}
      </div>
    </main>
  );
}

function Campo(props: { etiqueta: string; valor: string; cambiar: (v: string) => void; tipo?: string; ayuda?: string; auto?: string; mayus?: boolean }) {
  return (
    <label className="campo">
      <span>{props.etiqueta}</span>
      <input
        type={props.tipo ?? "text"}
        value={props.valor}
        autoComplete={props.auto}
        autoCapitalize={props.mayus ? "characters" : "off"}
        onChange={(e) => props.cambiar(e.target.value)}
        required
      />
      {props.ayuda && <small>{props.ayuda}</small>}
    </label>
  );
}

function Entrar({ alIniciar }: { alIniciar: (s: Sesion) => void }) {
  const [codigo, setCodigo] = useState("");
  const [usuario, setUsuario] = useState("");
  const [clave, setClave] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError("");
    setCargando(true);
    try {
      const r = await pedir<Sesion>("/auth/login", { json: { codigo_empresa: codigo, username: usuario, password: clave }, token: "" });
      alIniciar({ ...r, codigo_acceso: codigo.trim() }); // se recuerda para mostrarlo en el panel
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCargando(false);
    }
  }

  return (
    <form onSubmit={enviar}>
      <h1>Iniciar sesión</h1>
      <Campo etiqueta="Código del restaurante" valor={codigo} cambiar={(v) => setCodigo(v.toUpperCase())} mayus ayuda="Son 8 letras y números." />
      <Campo etiqueta="Usuario" valor={usuario} cambiar={setUsuario} auto="username" />
      <Campo etiqueta="Contraseña" valor={clave} cambiar={setClave} tipo="password" auto="current-password" />
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={cargando}>{cargando ? "Entrando…" : "Entrar"}</button>
    </form>
  );
}

function Crear({ alCrear }: { alCrear: (s: Sesion) => void }) {
  const [f, setF] = useState({ restaurante: "", sucursal: "Casa matriz", nombre: "", usuario: "", clave: "", pais: "CL", moneda: "CLP" });
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
          json: {
            nombre_restaurante: f.restaurante, sucursal: f.sucursal, admin_nombre: f.nombre, admin_usuario: f.usuario,
            password: f.clave, pais: f.pais, moneda: f.moneda,
          },
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
      <Campo etiqueta="Tu usuario" valor={f.usuario} cambiar={poner("usuario")} auto="username" ayuda="Con él iniciarás sesión." />
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

function CodigoNuevo({ sesion, continuar }: { sesion: Sesion; continuar: () => void }) {
  return (
    <main className="centro">
      <div className="tarjeta">
        <Marca />
        <h1>¡Tu restaurante está listo!</h1>
        <p className="suave">Este es el código de tu restaurante. Tu equipo lo necesita, junto con su usuario y contraseña, para entrar.</p>
        <div className="codigo" aria-label="Código de acceso">{sesion.codigo_acceso}</div>
        <p className="suave">Anótalo. Siempre podrás verlo después en el panel.</p>
        <button onClick={continuar}>Ir a mi panel</button>
      </div>
    </main>
  );
}
