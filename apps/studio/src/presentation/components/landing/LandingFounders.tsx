"use client";

import { motion } from "framer-motion";
import { useTranslation } from "@/i18n";
import { FOUNDERS_LIST } from "./data";

export default function LandingFounders() {
  const { t } = useTranslation();

  const founders = [
    {
      ...FOUNDERS_LIST[0],
      name: t("landing.founders.valerya.name", "Dra. Valerya Vance"),
      role: t("landing.founders.valerya.role", "Lead Audio DSP & Machine Learning Architect"),
      badge: t("landing.founders.valerya.badge", "DSP & ML CORE"),
      bio: t(
        "landing.founders.valerya.bio",
        "Especialista en redes neuronales espectrales y tensores en C++/Rust. Lideró la concepción del motor AudioMind y la simulación matemática de la resonancia de salas no-lineales."
      ),
      quote: t("landing.founders.valerya.quote", "“El sonido tiene memoria; la IA solo la despierta.”"),
      badgeClass: "bg-primary/20 text-primary border-primary/30",
      quoteBorder: "border-primary",
    },
    {
      ...FOUNDERS_LIST[1],
      name: t("landing.founders.kaelen.name", "Kaelen Thorne"),
      role: t("landing.founders.kaelen.role", "Full-Stack & Systems Infrastructure Lead"),
      badge: t("landing.founders.kaelen.badge", "INFRASTRUCTURE LEAD"),
      bio: t(
        "landing.founders.kaelen.bio",
        "Arquitecto del monorepo Next.js 16 + React 19 y FastAPI con WebSockets a 48 kHz. Ha diseñado el pipeline de streaming distribuido que procesa audio a escala masiva sin pérdida de paquetes."
      ),
      quote: t("landing.founders.kaelen.quote", "“Rendimiento implacable: cada microsegundo cuenta.”"),
      badgeClass: "bg-secondary/20 text-secondary border-secondary/30",
      quoteBorder: "border-secondary",
    },
    {
      ...FOUNDERS_LIST[2],
      name: t("landing.founders.dante.name", "Dante O'Connor"),
      role: t("landing.founders.dante.role", "Head of Sound Design & Product Experience"),
      badge: t("landing.founders.dante.badge", "SOUND DESIGN & UX"),
      bio: t(
        "landing.founders.dante.bio",
        "Con más de 20 años en mastering analógico, calibración de curvas psicoacústicas Haas y supervisión de UX/UI. Garantiza que la calidez de los transformadores valvulares trascienda al plano virtual."
      ),
      quote: t("landing.founders.dante.quote", "“La calidez analógica no se simula: se invoca.”"),
      badgeClass: "bg-tertiary-container/20 text-tertiary-container border-tertiary-container/30",
      quoteBorder: "border-tertiary-container",
    },
  ];

  return (
    <section
      className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#0d0e12] border-t border-white/[0.04] relative overflow-hidden"
      id="equipo-fundador"
    >
      {/* Ambient background glow */}
      <div
        className="absolute bottom-0 right-10 w-96 h-96 bg-primary/5 rounded-full blur-[140px] pointer-events-none"
        aria-hidden="true"
      />

      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header */}
        <div className="flex flex-col gap-2 max-w-3xl">
          <span className="font-label-technical text-primary text-[10px] uppercase tracking-widest">
            {t("landing.founders.badge", "Arquitectos del Sonido")}
          </span>
          <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
            {t("landing.founders.title", "El Aquelarre Técnico — Equipo Fundador de Brik")}
          </h2>
          <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
            {t(
              "landing.founders.subtitle",
              "Las 3 mentes que combinan ciencia acústica, algoritmos neuronales y experiencia de software para masterizar con fidelidad espectral."
            )}
          </p>
        </div>

        {/* 3 Founders Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8">
          {founders.map((founder, idx) => (
            <motion.div
              key={founder.id}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: idx * 0.1 }}
              className="flex flex-col bg-[#1a1b20] rounded-2xl overflow-hidden shadow-2xl border border-white/5 hover:border-white/15 transition-all duration-300 hover:-translate-y-1.5"
            >
              {/* Photo Viewport */}
              <div className="w-full h-80 relative overflow-hidden bg-[#292a2e]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={founder.image}
                  alt={founder.alt}
                  className="w-full h-full object-cover transition-transform duration-500 hover:scale-105"
                  loading="lazy"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-[#1a1b20] via-[#1a1b20]/30 to-transparent" />
                <div className="absolute top-4 left-4 z-10">
                  <span
                    className={`font-label-technical text-[10px] px-3 py-1 rounded-full backdrop-blur-md font-semibold border ${founder.badgeClass}`}
                  >
                    {founder.badge}
                  </span>
                </div>
              </div>

              {/* Bio & Quote Details */}
              <div className="p-6 sm:p-8 flex flex-col justify-between flex-grow gap-5 -mt-6 z-10">
                <div className="flex flex-col gap-1.5">
                  <h3 className="font-headline-md text-xl sm:text-2xl font-bold text-[#e3e2e8]">
                    {founder.name}
                  </h3>
                  <span className="font-label-technical text-xs text-primary font-semibold">
                    {founder.role}
                  </span>
                  <p className="font-body-sm text-xs text-[#bcc9c7] mt-2.5 leading-relaxed">
                    {founder.bio}
                  </p>
                </div>

                <div
                  className={`p-4 rounded-xl bg-[#292a2e]/80 border-l-2 ${founder.quoteBorder} shadow-inner`}
                >
                  <p className="font-body-md text-xs italic text-[#e3e2e8]">
                    {founder.quote}
                  </p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
