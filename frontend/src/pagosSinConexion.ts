// ============================================================
// YEPAR RESTAURANT — frontend/src/pagosSinConexion.ts
// Modo sin conexión de la CAJA: solo los cobros viajan por una cola.
// Analogía: el talonario de recibos. Si se cae la red, el cajero sigue entregando recibos numerados;
// cuando vuelve la red, los recibos viajan al servidor en orden. Cada recibo lleva su número único
// (pago_id), así que si el servidor ya lo tenía, lo reconoce y no cobra dos veces.
// Qué NO se hace sin red (a propósito): propina, descuento (necesita PIN de supervisor), cerrar turno
// y entregar propinas. Son decisiones que cambian el total o el arqueo: se hacen con el servidor al lado.
// ============================================================
import { useSyncExternalStore } from "react";
import { ErrorApi, pedir } from "./api";
import { fijarUsuario } from "./sinConexion";

export type PagoPendiente = {
  pago_id: string;
  pedido_id: string;
  mesa: string | null;
  medio: "efectivo" | "tarjeta" | "transferencia";
  monto: string;
  creado: number;
  json: Record<string, unknown>;           // el cuerpo exacto que viajará a POST /pedidos/{id}/pagos
};
export type PagoRechazado = { pago_id: string; mesa: string | null; monto: string; error: string };
export type EstadoPagos = { cola: PagoPendiente[]; rechazados: PagoRechazado[]; enviando: boolean; version: number };

let uid: number | null = null;
let estado: EstadoPagos = { cola: [], rechazados: [], enviando: false, version: 0 };
const oyentes = new Set<() => void>();

const clave = (nombre: string) => `yepar_caja_${nombre}_${uid}`;
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
    /* sin almacenamiento: la cola vive en memoria mientras la pestaña siga abierta */
  }
}
function cambiar(parcial: Partial<EstadoPagos>) {
  estado = { ...estado, ...parcial, version: estado.version + 1 };
  oyentes.forEach((f) => f());
}
function persistir() {
  guardar("pagos", estado.cola);
  guardar("rechazados", estado.rechazados);
}

/** Fija de quién es la caja y carga sus cobros pendientes. Síncrona: la primera pantalla ya los ve. */
export function fijarCajero(usuarioId: number) {
  if (uid === usuarioId) return;
  uid = usuarioId;
  fijarUsuario(usuarioId);                  // comparte la copia local (mesas, cuentas) con el modo del mesero
  estado = { ...estado, cola: leer<PagoPendiente[]>("pagos", []), rechazados: leer<PagoRechazado[]>("rechazados", []), version: estado.version + 1 };
  oyentes.forEach((f) => f());
}

/** Al entrar a la caja: intenta enviar lo que haya quedado. También al volver la red. */
export function iniciarPagos(usuarioId: number) {
  fijarCajero(usuarioId);
  void enviarPagos();
}
if (typeof window !== "undefined") window.addEventListener("online", () => void enviarPagos());

export function anotarPago(p: Omit<PagoPendiente, "creado">) {
  cambiar({ cola: [...estado.cola, { ...p, creado: Date.now() }] });
  persistir();
}

export function descartarRechazados() {
  cambiar({ rechazados: [] });
  persistir();
}

/** Cobros anotados que aún no viajaron (lectura fresca, fuera de React). */
export const colaActual = () => estado.cola;

/** Lo ya anotado sin enviar para una cuenta (para restarlo del pendiente que se muestra). */
export function pendienteDeEnvio(pedidoId: string, cola: PagoPendiente[]): number {
  return cola.filter((p) => p.pedido_id === pedidoId).reduce((s, p) => s + Number(p.monto), 0);
}

let enCurso: Promise<void> | null = null;
/** Envía los cobros en orden. Sin red o con el servidor caído, se queda todo y se reintenta. */
export function enviarPagos(): Promise<void> {
  if (enCurso) return enCurso;
  if (uid === null || estado.cola.length === 0) return Promise.resolve();
  enCurso = (async () => {
    cambiar({ enviando: true });
    try {
      while (estado.cola.length > 0) {
        const p = estado.cola[0];
        try {
          await pedir(`/pedidos/${p.pedido_id}/pagos`, { json: p.json });
        } catch (e) {
          if (!(e instanceof ErrorApi)) throw e;
          if (e.estado === 0 || e.estado >= 500) throw e;              // sin red o servidor caído: reintentar luego
          // "Ese pago ya existe": el primer intento sí llegó y solo se perdió la respuesta → ya está cobrado.
          if (!/ya existe/i.test(e.message)) {
            cambiar({ rechazados: [...estado.rechazados, { pago_id: p.pago_id, mesa: p.mesa, monto: p.monto, error: e.message }] });
          }
        }
        cambiar({ cola: estado.cola.filter((x) => x.pago_id !== p.pago_id) });
        persistir();
      }
    } catch {
      /* se queda en la cola; el siguiente intento lo retoma */
    } finally {
      cambiar({ enviando: false });
      enCurso = null;
    }
  })();
  return enCurso;
}

export function usePagosSinConexion(): EstadoPagos {
  return useSyncExternalStore(
    (f) => { oyentes.add(f); return () => { oyentes.delete(f); }; },
    () => estado,
  );
}
