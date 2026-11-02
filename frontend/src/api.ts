// ============================================================
// YEPAR RESTAURANT — frontend/src/api.ts
// El "teléfono" de la web hacia la API: pone la dirección, manda la sesión y traduce los errores
// a frases que una persona entienda. La sesión se guarda en el navegador de quien la inicia.
// ============================================================

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Usuario = { id: number; nombre: string; roles: string[]; estacion: string | null; sucursal_id: number | null };
export type Sesion = { access_token: string; usuario: Usuario; codigo_acceso?: string };

const CLAVE = "yepar_sesion";

export function leerSesion(): Sesion | null {
  try {
    const bruto = localStorage.getItem(CLAVE);
    return bruto ? (JSON.parse(bruto) as Sesion) : null;
  } catch {
    return null; // modo privado o almacenamiento bloqueado: la web funciona igual, solo no recuerda la sesión
  }
}

export function guardarSesion(s: Sesion | null) {
  try {
    if (s) localStorage.setItem(CLAVE, JSON.stringify(s));
    else localStorage.removeItem(CLAVE);
  } catch {
    /* sin almacenamiento: se queda solo en memoria */
  }
}

export class ErrorApi extends Error {
  constructor(mensaje: string, public estado: number, public cuerpo?: unknown) {
    super(mensaje);
  }
}

/** La API responde errores en tres formas: {detalle}, {detail: "texto"} y {detail: [{msg, loc}]} (validación). */
function mensajeDe(estado: number, cuerpo: any): string {
  if (typeof cuerpo?.detalle === "string") return cuerpo.detalle;
  if (typeof cuerpo?.detail === "string") return cuerpo.detail;
  if (Array.isArray(cuerpo?.detail) && cuerpo.detail.length) {
    const d = cuerpo.detail[0];
    const campo = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
    return campo ? `${campo}: ${d.msg}` : String(d.msg);
  }
  if (estado === 401) return "Tu sesión terminó. Entra de nuevo.";
  if (estado === 429) return "Demasiados intentos. Espera un momento.";
  return `Error inesperado (${estado}).`;
}

let alExpirar: () => void = () => {};
export function alExpirarSesion(fn: () => void) {
  alExpirar = fn;
}

export async function pedir<T>(ruta: string, opciones: { metodo?: string; json?: unknown; form?: FormData; token?: string } = {}): Promise<T> {
  const token = opciones.token ?? leerSesion()?.access_token;
  const cabeceras: Record<string, string> = {};
  if (token) cabeceras.Authorization = `Bearer ${token}`;
  let cuerpo: BodyInit | undefined;
  if (opciones.json !== undefined) {
    cabeceras["Content-Type"] = "application/json";
    cuerpo = JSON.stringify(opciones.json);
  } else if (opciones.form) {
    cuerpo = opciones.form;
  }
  let r: Response;
  try {
    r = await fetch(`${API_URL}${ruta}`, { method: opciones.metodo ?? (cuerpo ? "POST" : "GET"), headers: cabeceras, body: cuerpo });
  } catch {
    throw new ErrorApi("No se pudo conectar con el servidor. Revisa tu conexión.", 0);
  }
  if (r.status === 204) return undefined as T;
  const datos = await r.json().catch(() => null);
  if (!r.ok) {
    if (r.status === 401 && token) alExpirar();
    throw new ErrorApi(mensajeDe(r.status, datos), r.status, datos);
  }
  return datos as T;
}

/** Descarga un archivo protegido (la plantilla de Excel): hay que pedirlo con la sesión y guardarlo como blob. */
export async function descargar(ruta: string, nombre: string) {
  const r = await fetch(`${API_URL}${ruta}`, { headers: { Authorization: `Bearer ${leerSesion()?.access_token ?? ""}` } });
  if (!r.ok) throw new ErrorApi("No se pudo descargar el archivo.", r.status);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}
