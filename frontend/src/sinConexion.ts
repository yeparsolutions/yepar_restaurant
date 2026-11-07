// ============================================================
// YEPAR RESTAURANT — frontend/src/sinConexion.ts
// Modo sin conexión de la tablet del mesero.
// Analogía: la libreta con copia al carbón. Todo lo que el mesero hace se anota primero en la tablet
// (una cola de operaciones con su número único); cuando hay red, la cola viaja al servidor en orden.
// Si el servidor ya había recibido una hoja, la reconoce por su número y no la repite.
// ============================================================
import { useSyncExternalStore } from "react";
import { ErrorApi, pedir } from "./api";

export const nuevoId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`);

export type TipoOperacion = "abrir_pedido" | "tomar_linea" | "quitar_linea" | "enviar" | "cancelar_linea" | "pedir_cuenta" | "anular_pedido";
export type Operacion = { op_id: string; tipo: TipoOperacion; datos: Record<string, unknown>; creada: number };
export type Rechazo = { op_id: string; tipo: string; error: string };
type Resultado = { op_id: string; tipo: string; estado: "aplicada" | "rechazada"; error: string | null };

export type EstadoCola = { cola: Operacion[]; rechazadas: Rechazo[]; enviando: boolean; enLinea: boolean; version: number };

let uid: number | null = null;
let estado: EstadoCola = { cola: [], rechazadas: [], enviando: false, enLinea: typeof navigator === "undefined" ? true : navigator.onLine, version: 0 };
const oyentes = new Set<() => void>();

// ── Almacenamiento (cada persona tiene su propia cola) ──────
const clave = (nombre: string) => `yepar_${nombre}_${uid}`;
function leer<T>(nombre: string, defecto: T): T {
  try {
    const bruto = localStorage.getItem(clave(nombre));
    return bruto ? (JSON.parse(bruto) as T) : defecto;
  } catch {
    return defecto;
  }
}
function guardar(nombre: string, valor: unknown) {
  try {
    localStorage.setItem(clave(nombre), JSON.stringify(valor));
  } catch {
    /* sin almacenamiento: la cola vive solo en memoria mientras la pestaña siga abierta */
  }
}

/** Copia local de lo último que se vio (plano, carta, pedidos) para poder trabajar sin red. */
export function guardarCache(nombre: string, datos: unknown) {
  if (uid !== null) guardar("cache_" + nombre, datos);
}
export function leerCache<T>(nombre: string): T | null {
  return uid === null ? null : leer<T | null>("cache_" + nombre, null);
}

function cambiar(parcial: Partial<EstadoCola>) {
  estado = { ...estado, ...parcial, version: estado.version + 1 };
  oyentes.forEach((f) => f());
}
function persistir() {
  guardar("cola", estado.cola);
  guardar("rechazadas", estado.rechazadas);
}

/** Fija de quién es la tablet y carga su cola y su copia local. Es síncrona para que la primera pantalla ya pueda leer la copia. */
export function fijarUsuario(usuarioId: number) {
  if (uid === usuarioId) return;
  uid = usuarioId;
  estado = { ...estado, cola: leer<Operacion[]>("cola", []), rechazadas: leer<Rechazo[]>("rechazadas", []), version: estado.version + 1 };
  oyentes.forEach((f) => f());
}

/** Se llama al entrar a la pantalla del mesero: intenta enviar lo que haya quedado en la cola. */
export function iniciarSinConexion(usuarioId: number) {
  fijarUsuario(usuarioId);
  void vaciarCola();
}

export function marcarConexion(enLinea: boolean) {
  if (estado.enLinea !== enLinea) cambiar({ enLinea });
}
if (typeof window !== "undefined") {
  window.addEventListener("online", () => { marcarConexion(true); void vaciarCola(); });
  window.addEventListener("offline", () => marcarConexion(false));
}

// ── La cola ──────────────────────────────────────────────────
export function encolar(tipo: TipoOperacion, datos: Record<string, unknown>) {
  cambiar({ cola: [...estado.cola, { op_id: nuevoId(), tipo, datos, creada: Date.now() }] });
  persistir();
  void vaciarCola();
}

/** Saca de la cola una operación que todavía no salió (p. ej. un plato anotado y tachado antes de sincronizar). */
export function descartarSiNoSalio(coincide: (o: Operacion) => boolean): boolean {
  if (estado.enviando) return false;                 // quizá ya viajó: mejor registrar la anulación
  const resto = estado.cola.filter((o) => !coincide(o));
  if (resto.length === estado.cola.length) return false;
  cambiar({ cola: resto });
  persistir();
  return true;
}

export function descartarRechazadas() {
  cambiar({ rechazadas: [] });
  persistir();
}

let enCurso: Promise<void> | null = null;
/** Envía la cola al servidor en orden. Si no hay red, la deja intacta para el próximo intento. */
export function vaciarCola(): Promise<void> {
  if (enCurso) return enCurso;
  if (uid === null || estado.cola.length === 0) return Promise.resolve();
  enCurso = (async () => {
    cambiar({ enviando: true });
    try {
      while (estado.cola.length > 0) {
        const lote = estado.cola.slice(0, 200);
        const r = await pedir<{ resultados: Resultado[] }>("/sync/operaciones", {
          json: { operaciones: lote.map(({ op_id, tipo, datos }) => ({ op_id, tipo, datos })) },
        });
        const salieron = new Set(r.resultados.map((x) => x.op_id));
        const nuevas: Rechazo[] = r.resultados.filter((x) => x.estado === "rechazada").map((x) => ({ op_id: x.op_id, tipo: x.tipo, error: x.error ?? "Rechazada." }));
        cambiar({ cola: estado.cola.filter((o) => !salieron.has(o.op_id)), rechazadas: [...estado.rechazadas, ...nuevas], enLinea: true });
        persistir();
        if (r.resultados.length === 0) break;       // defensa: no dar vueltas si el servidor no confirmó nada
      }
    } catch (e) {
      // Sin red (estado 0) o servidor caído: la cola se queda y se reintenta sola.
      if (e instanceof ErrorApi && e.estado === 0) cambiar({ enLinea: false });
    } finally {
      cambiar({ enviando: false });
      enCurso = null;
    }
  })();
  return enCurso;
}

export function useSinConexion(): EstadoCola {
  return useSyncExternalStore(
    (f) => { oyentes.add(f); return () => { oyentes.delete(f); }; },
    () => estado,
  );
}
