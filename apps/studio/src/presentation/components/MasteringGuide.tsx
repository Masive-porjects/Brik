"use client";

import { useTranslation } from "@/i18n";

const PIPELINE_STEPS = [
  {
    step: "01",
    title: "Gain Staging",
    description:
      "Normalizamos la señal de entrada a un headroom consistente de -6 dBFS. Esto asegura que todos los módulos DSP trabajen con el mismo margen dinámico, independientemente de qué tan fuerte o suave sea tu mezcla original.",
  },
  {
    step: "02",
    title: "Match EQ (Corrección Espectral por Género)",
    description:
      "Analizamos el contenido espectral de tu audio y lo comparamos con perfiles objetivo de la industria comercial. Cada género tiene una 'firma espectral ideal' — el Match EQ empuja tu mezcla hacia ese target sin aplanar el carácter único de tu música.",
  },
  {
    step: "03",
    title: "Compresión Proporcional",
    description:
      "El umbral de compresión se calcula dinámicamente a partir del RMS real de tu audio. La relación la controlas tú con el módulo 'Fuego / Empuje'. Más ratio = más control de picos; menos ratio = más dinámica natural.",
  },
  {
    step: "04",
    title: "Procesamiento M/S (Mid/Side)",
    description:
      "Separamos la señal en canal Central (Mid, todo lo que suena en mono) y Lateral (Side, todo lo que suena en estéreo). Esto permite procesar la reverberación, el ancho estéreo y el delay Haas de forma independiente sin ensuciar el centro.",
  },
  {
    step: "05",
    title: "Saturación Armónica (THD)",
    description:
      "Aplicamos distorsión armónica controlada simulando cinta analógica. El módulo 'Cinta / Saturación' te permite inyectar calidez y armónicos pares (al estilo cinta magnética) que el oído humano percibe como 'musicales' y 'cálidos'.",
  },
  {
    step: "06",
    title: "True Peak Limiting (4x Oversampling)",
    description:
      "El limitador final trabaja con sobremuestreo 4x para atrapar picos entre muestras (inter-sample peaks) que los limitadores estándar no ven. Combinado con el Codec Pre-Matching, ajustamos el techo dinámicamente para evitar distorsión en streaming.",
  },
  {
    step: "07",
    title: "Noise-Shaped Dithering (Lipshitz 2nd Order)",
    description:
      "Al exportar en 16 bits, aplicamos dither con modelado de ruido de 2do orden (Lipshitz) que empuja el piso de ruido de cuantización por encima de 15 kHz, donde el oído humano es menos sensible. El resultado: audio de 16 bits que suena como si fuera de 24.",
  },
];

const TIPS = [
  {
    title: "Deja headroom en tu mezcla",
    body: "Exporta tu mezcla con picos entre -6 dBFS y -3 dBFS. NO subas el master fader de tu DAW. El headroom le da espacio al motor DSP de WaveIA para trabajar sin recortar transitorios.",
  },
  {
    title: "No apliques limitación en el bus maestro",
    body: "Si ya limitaste la mezcla en tu DAW, el motor no puede diferenciar entre tu intención creativa y la distorsión. Deja el bus maestro limpio — WaveIA se encarga de la limitación final profesional.",
  },
  {
    title: "Exporta en WAV de 24 bits",
    body: "El formato WAV de 24-bit a 44.1 kHz o 48 kHz es el estándar de la industria. Evitá MP3, AAC u otros formatos con pérdida — el algoritmo necesita la información completa para procesar correctamente.",
  },
  {
    title: "Verificá que el bajo no esté saturado en mono",
    body: "Las frecuencias bajo 120 Hz se convierten a mono automáticamente para evitar problemas de fase en vinilo y sistemas club. Si tu bajo ya tiene problemas de fase, escuchalo en mono ANTES de subir el archivo.",
  },
];

export default function MasteringGuide() {
  const { t } = useTranslation();

  return (
    <div className="space-y-8">
      {/* Pipeline */}
      <section>
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1" style={{ letterSpacing: "-0.02em" }}>
          {t("pipeline.title", "Cadena de")}{" "}
          <span className="serif-accent">{t("pipeline.titleAccent", "Master")}</span>
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-5">
          {t("pipeline.subtitle", "Cómo funciona WaveIA paso a paso — cadena DSP profesional")}
        </p>

        <div className="space-y-3">
          {PIPELINE_STEPS.map((step) => {
            const localizedTitle = t(`pipeline.steps.${step.step}.title`, step.title);
            const localizedDesc = t(`pipeline.steps.${step.step}.description`, step.description);

            return (
              <div
                key={step.step}
                className="flex gap-4 p-4 rounded-xl transition-colors hover:bg-[var(--surface-hover)]"
                style={{
                  background: "var(--surface-hover)",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                <span
                  className="text-xs font-bold font-mono w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                  style={{
                    background: "rgba(98, 126, 132, 0.1)",
                    color: "var(--accent-primary)",
                  }}
                >
                  {step.step}
                </span>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1">{localizedTitle}</h3>
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{localizedDesc}</p>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Tips */}
      <section>
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1" style={{ letterSpacing: "-0.02em" }}>
          {t("pipeline.tipsTitle", "Tips para un Master Exitoso")}
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-5">
          {t("pipeline.tipsSubtitle", "Antes de subir tu audio, revisá estos puntos")}
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {TIPS.map((tip, idx) => {
            const localizedTipTitle = t(`pipeline.tips.${idx}.title`, tip.title);
            const localizedTipBody = t(`pipeline.tips.${idx}.body`, tip.body);

            return (
              <div
                key={tip.title}
                className="p-4 rounded-xl"
                style={{
                  background: "var(--surface-hover)",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                <h3 className="text-sm font-semibold text-[var(--accent-primary)] mb-2">
                  {localizedTipTitle}
                </h3>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{localizedTipBody}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* Authorship */}
      <section
        className="rounded-xl p-6 text-center"
        style={{
          background: "linear-gradient(135deg, rgba(98,126,132,0.06) 0%, rgba(130,156,161,0.06) 100%)",
          border: "1px solid rgba(98,126,132,0.12)",
        }}
      >
        <div
          className="w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-3"
          style={{ background: "rgba(98, 126, 132, 0.1)" }}
        >
          <span className="text-lg">🎧</span>
        </div>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-2xl mx-auto">
          {t(
            "pipeline.authorship",
            "Brikman Paul, el creador de WaveIA, se ha tomado el trabajo de pulir meticulosamente cada algoritmo y modelo matemático DSP para garantizar que cada canción que pase por la plataforma suene superbién, competitiva y lista para la industria musical internacional."
          )}
        </p>
      </section>
    </div>
  );
}
