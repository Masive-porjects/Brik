# Lineamientos de Multiidioma y Estética Visual de WaveIA

Este documento define las reglas de estricto cumplimiento para cualquier nueva pantalla, componente o integración en el proyecto **WaveIA**.

---

## 1. Multiidioma Obligatorio (i18n)

1. **Uso Exclusivo de `useTranslation`**:
   - Todo texto legible por el usuario en componentes de React (`apps/studio/`) debe consumirse mediante:
     ```tsx
     const { t } = useTranslation();
     // Uso:
     t("modulo.claveTexto", "Texto de respaldo")
     ```
2. **Registro Bilingüe Simultáneo**:
   - Cada clave creada debe agregarse en:
     - `apps/studio/src/i18n/locales/es.json` (Español neutro / latinoamericano sin voseo).
     - `apps/studio/src/i18n/locales/en.json` (Inglés nativo profesional).
3. **Cero Spanglish**:
   - Queda prohibida la mezcla de idiomas en una misma vista o frase. Si la aplicación está en español, el 100% de títulos, subtítulos, botones, placeholders y mensajes de error deben estar en español.
4. **Validaciones y Mensajes de Error**:
   - Los mensajes de validación (Zod, React Hook Form, o respuestas de servidor) deben estar traducidos y no mostrar errores técnicos crudos al usuario final.

---

## 2. Estética Visual y Design System WaveIA

1. **Tokens de Color y Superficies**:
   - Emplear siempre las variables CSS del sistema en lugar de estilos hardcodeados o colores estándar de Tailwind:
     - Superficies: `var(--bg-base)`, `var(--surface-elevated)`, `var(--bg-glass-elevated)`
     - Acentos: `var(--accent-primary)`, `var(--accent-secondary)`
     - Textos: `var(--text-primary)`, `var(--text-secondary)`, `var(--text-muted)`
     - Bordes: `var(--border-subtle)`, `var(--border-strong)`
2. **Glassmorphism y Efectos Premium**:
   - Fondos semitransparentes con `backdrop-blur-xl` o `backdrop-blur-2xl`.
   - Sombras profundas (`box-shadow: 0 24px 60px -15px rgba(0,0,0,0.6)`).
   - Bordes sutiles con iluminación superior (`inset 0 1px 0 rgba(255,255,255,0.08)`).
3. **Identidad de Marca WaveIA**:
   - Incorporar los elementos icónicos de WaveIA en vistas de acceso, carga o estados clave:
     - Mascota fantasma interactiva (`BigGhostWithNotes`, `FloatingGhosts`).
     - Notas musicales flotantes (`FloatingNotes`).
     - Gradientes radiales de luz mística (tonos cyan / púrpura / violeta).
4. **Tipografía Oficial**:
   - `Inter` (`wght 300, 400, 500, 600, 700`): Para toda la interfaz de usuario, etiquetas técnicas, tablas y controles.
   - `Instrument Serif`: Usada para titulares estilizados y detalles de marca.
   - Fuentes Monoespaciadas (`ui-monospace`, `Courier New` o similar): Para lecturas numéricas de precisión (LUFS, dBTP, BPM, Hz, Sample Rate).
5. **Medidores y LEDs Acústicos**:
   - Seguro (Safe): `#34c759` (Verde analógico).
   - Precaución (Warn): `#ff9500` (Ámbar cálido).
   - Clipping / Alerta (Clip): `#ff3b30` / `#dc2626` (Rojo crítico).
6. **Ergonomía y Cero Scroll**:
   - Pantallas como `/login`, `/register`, modales de confirmación o paneles de diálogo deben diseñarse para ajustarse completamente en la ventana (`h-screen max-h-screen overflow-hidden` o contenido centrado) sin generar barras de desplazamiento vertical en resoluciones comunes de escritorio/laptop.
7. **Micro-interacciones y Animaciones Fluidas**:
   - Uso de `framer-motion` para transiciones de entrada (`initial`, `animate`, `exit`) y alternancia de vistas con `AnimatePresence`.
   - Micro-indicadores visuales interactivos en tiempo real (como los estados de validación de contraseñas, hover en tarjetas, loaders en botones).

---

## 3. Cursor Interactivo y Accesibilidad
1. **Cursor Pointer Obligatorio**:
   - Todo elemento accionable (botones, tarjetas clickeables, pestañas, modales, selectores y controles) debe mostrar obligatoriamente `cursor: pointer`.
   - Elementos deshabilitados deben mostrar `cursor: not-allowed`.
