// ============================================================
// YEPAR RESTAURANT — frontend/src/dinero.ts
// Cómo se muestran los montos según la moneda del restaurante (CLP, VES, USD…).
// La moneda se pide una vez al entrar (GET /auth/empresa) y se recuerda en la tablet para trabajar sin conexión.
// ============================================================

const CLAVE = "yepar_moneda";

// Símbolo, decimales y forma de agrupar miles de cada moneda conocida. Una moneda desconocida usa su código.
const MONEDAS: Record<string, { simbolo: string; decimales: number; locale: string }> = {
  CLP: { simbolo: "$", decimales: 0, locale: "es-CL" },
  VES: { simbolo: "Bs. ", decimales: 2, locale: "es-VE" },
  VED: { simbolo: "Bs. ", decimales: 2, locale: "es-VE" },
  USD: { simbolo: "US$ ", decimales: 2, locale: "en-US" },
  COP: { simbolo: "$", decimales: 0, locale: "es-CO" },
  PEN: { simbolo: "S/ ", decimales: 2, locale: "es-PE" },
  ARS: { simbolo: "$", decimales: 2, locale: "es-AR" },
  MXN: { simbolo: "$", decimales: 2, locale: "es-MX" },
  EUR: { simbolo: "€", decimales: 2, locale: "es-ES" },
};

let moneda = leer();

function leer(): string {
  try {
    return localStorage.getItem(CLAVE) || "CLP";
  } catch {
    return "CLP";
  }
}

export function monedaActual(): string {
  return moneda;
}

/** Fija la moneda con que se muestran los montos y la recuerda para la próxima vez (también sin conexión). */
export function fijarMoneda(codigo: string | null | undefined) {
  const c = (codigo || "").trim().toUpperCase();
  if (!c) return;
  moneda = c;
  try {
    localStorage.setItem(CLAVE, c);
  } catch {
    /* sin almacenamiento: vale para esta sesión */
  }
}

/** Un monto con el símbolo de la moneda y los decimales que le corresponden. */
export function plata(v: string | number | null | undefined, opciones: { enteros?: boolean } = {}): string {
  const n = Number(v ?? 0);
  const cfg = MONEDAS[moneda] ?? { simbolo: `${moneda} `, decimales: 2, locale: "es-CL" };
  const decimales = opciones.enteros ? 0 : cfg.decimales;
  const texto = Math.abs(n).toLocaleString(cfg.locale, { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  return (n < 0 ? "−" : "") + cfg.simbolo + texto;
}
