"use client";

import { useTranslation } from "@/i18n";

const GENRES = [
  {
    id: "urban",
    name: "Urban / Hip-Hop / Reggaetón",
    emoji: "🎤",
    color: "#ff6b35",
    description:
      "El sonido urbano moderno se caracteriza por la DOMINANCIA del sub-bass entre 50–80 Hz. En el mastering comercial para streaming, la densidad se controla con transitorios afinados para mantener la energía sin pasar del techo seguro de loudness (target -12 LUFS integrados y true-peak en -1 dBTP). Así el master suena caliente y consistente sin que Spotify/Apple/YouTube lo atenúen ni le sumen distorsión. La imagen estéreo tiende a ser angosta en las bajas frecuencias y abierta en los agudos, con una compresión del bus maestro que mantiene el ritmo constante y la energía sin picos disruptivos.",
    details: [
      "Sub-bass profundo y controlado (60 Hz con alta densidad espectral)",
      "Transitorios recortados para maximizar LUFS sin distorsión audible",
      "Side chain rítmico en el bajo para dar espacio al kick",
      "Vocales al frente con presencia en 2–4 kHz",
    ],
  },
  {
    id: "rock",
    name: "Rock / Indie",
    emoji: "🎸",
    color: "#ff3b30",
    description:
      "El mastering de rock busca preservar la AGRESIVIDAD natural de la batería y las guitarras, con un énfasis en los medios-graves (200–500 Hz) que dan peso y calidez. La compresión es moderada comparada con el urbano — se busca el 'punch' orgánico antes que la densidad absoluta. La imagen estéreo es ancha, aprovechando guitarras paneadas y overheads de batería para crear un muro de sonido envolvente.",
    details: [
      "Batería con ataque natural y cola de resonancia preservada",
      "Guitarras con presencia en medios-agudos (2–4 kHz) sin aspereza",
      "Compresión suave (2:1 a 3:1) que mantiene la dinámica de la interpretación",
      "Rango dinámico amplio (8–12 dB) comparado con otros géneros",
    ],
  },
  {
    id: "pop",
    name: "Pop / Electrónica",
    emoji: "✨",
    color: "#ffd700",
    description:
      "El pop comercial exige un BRILLO cristalino en las frecuencias altas (8–12 kHz) combinado con una compresión balanceada que mantenga la energía sin sacrificar claridad. La imagen estéreo es moderna y extendida, con pads y sintetizadores que llenan el espacio lateral mientras el kick y el bajo se mantienen sólidos en el centro. El target de loudness ronda los -13 a -14 LUFS integrados con true-peak en -1 dBTP, optimizado y seguro para streaming.",
    details: [
      "Brightness extensivo en el rango de 8–12 kHz para brillo 'air'",
      "Compresión multibanda suave para controlar picos sin bombear",
      "Imagen estéreo amplia con elementos de relleno en los extremos",
      "Transientes controlados pero presentes para mantener la energía rítmica",
    ],
  },
  {
    id: "jazz",
    name: "Jazz / Clásica",
    emoji: "🎻",
    color: "#34c759",
    description:
      "La música acústica y orquestal exige una PUREZA absoluta en la cadena de masterización. Aquí el objetivo NO es la loudness sino la preservación del rango dinámico original de la interpretación. La compresión se usa con extrema sutileza (1.1:1 a 1.5:1), solo para suavizar picos accidentales. El balance espectral busca ser plano y transparente, dejando que la acústica natural del espacio de grabación y la dinámica de los músicos sean protagonistas.",
    details: [
      "Mínima compresión — se preserva la dinámica natural (rango de 15–25 dB)",
      "Curva espectral plana sin realces artificiales en agudos ni graves",
      "Sin limitación agresiva — el ceiling se coloca en -2 dBFS o más abajo",
      "Reverberación natural del espacio de grabación se mantiene intacta",
    ],
  },
  {
    id: "latin",
    name: "Latino / Fusiones",
    emoji: "💃",
    color: "#00d4aa",
    description:
      "El género latino y sus fusiones requieren un BALANCE dinámico que permita a las percusiones vivas mantener su ataque natural mientras la voz se posiciona al frente con claridad. La cohesión rítmica es la prioridad — todos los elementos deben funcionar como un motor sincronizado. El rango de frecuencia es amplio, desde tumbadoras y congas en los medios hasta el bajo eléctrico o synth en las frecuencias graves, con una presencia vocal prominente en 3–5 kHz.",
    details: [
      "Percusiones con ataque preservado — no se sacrifican por loudness",
      "Vocal al frente con claridad en 3–5 kHz y calidez en 200–400 Hz",
      "Cohesión rítmica — compresión suave en el bus maestro que une la mezcla",
      "Ancho estéreo moderado que mantiene la energía bailable en mono",
    ],
  },
];

const COLORS = [
  "rgba(255, 107, 53, 0.06)",
  "rgba(98, 126, 132, 0.06)",
  "rgba(255, 215, 0, 0.06)",
  "rgba(52, 199, 89, 0.06)",
  "rgba(0, 212, 170, 0.06)",
];

export default function GenreGuide() {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1" style={{ letterSpacing: "-0.02em" }}>
          {t("genreGuide.title", "Géneros")}{" "}
          <span className="serif-accent">{t("genreGuide.titleAccent", "Musicales")}</span>
        </h2>
        <p className="text-sm text-[var(--text-secondary)]">
          {t("genreGuide.subtitle", "Cómo suena cada género en el mastering comercial — guía educativa")}
        </p>
      </div>

      {GENRES.map((genre, i) => {
        const localizedName = t(`genreGuide.genres.${genre.id}.name`, genre.name);
        const localizedDesc = t(`genreGuide.genres.${genre.id}.description`, genre.description);

        return (
          <div
            key={genre.id}
            className="rounded-xl p-5 transition-all duration-200 hover:brightness-110"
            style={{
              background: COLORS[i % COLORS.length],
              border: `1px solid ${genre.color}12`,
            }}
          >
            <div className="flex items-start gap-4">
              <span className="text-2xl mt-0.5">{genre.emoji}</span>
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-semibold text-[var(--text-primary)] mb-2">
                  {localizedName}
                </h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-3">
                  {localizedDesc}
                </p>
                <ul className="space-y-1.5">
                  {genre.details.map((detail, j) => (
                    <li key={j} className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
                      <span style={{ color: genre.color }}>▸</span>
                      {t(`genreGuide.genres.${genre.id}.details.${j}`, detail)}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        );
      })}

      <p className="text-[11px] text-[var(--text-muted)] text-center pt-2 italic">
        {t("genreGuide.footnote", "Basado en estándares de la industria de mastering comercial y análisis espectral de lanzamientos certificados.")}
      </p>
    </div>
  );
}

