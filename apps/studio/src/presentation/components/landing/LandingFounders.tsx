"use client";

import { motion } from "framer-motion";
import { Globe } from "lucide-react";
import { useTranslation } from "@/i18n";
import { GitHubIcon, LinkedInIcon } from "@/features/auth/components/SocialIcons";
import { FOUNDERS_LIST } from "./data";

export default function LandingFounders() {
  const { t } = useTranslation();

  const founders = FOUNDERS_LIST.map((founder) => {
    let badgeClass = "bg-primary/20 text-primary border-primary/30";
    let quoteBorder = "border-primary";

    if (founder.badgeColor === "secondary") {
      badgeClass = "bg-secondary/20 text-secondary border-secondary/30";
      quoteBorder = "border-secondary";
    } else if (founder.badgeColor === "tertiary") {
      badgeClass = "bg-tertiary-container/20 text-tertiary-container border-tertiary-container/30";
      quoteBorder = "border-tertiary-container";
    }

    return {
      ...founder,
      name: t(`landing.founders.${founder.id}.name`, founder.name),
      role: t(`landing.founders.${founder.id}.role`, founder.role),
      badge: t(`landing.founders.${founder.id}.badge`, founder.badge),
      bio: t(`landing.founders.${founder.id}.bio`, founder.bio),
      quote: t(`landing.founders.${founder.id}.quote`, founder.quote),
      badgeClass,
      quoteBorder,
    };
  });

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
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8 items-stretch">
          {founders.map((founder, idx) => {
            const hasSocials = Boolean(
              founder.socials?.linkedin || founder.socials?.github || founder.socials?.website
            );

            return (
              <motion.div
                key={founder.id}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: idx * 0.1 }}
                className="flex flex-col bg-[#1a1b20] rounded-2xl overflow-hidden shadow-2xl border border-white/5 hover:border-white/15 transition-all duration-300 hover:-translate-y-1.5 h-full"
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
                <div className="p-6 sm:p-7 xl:p-8 flex flex-col justify-between flex-1 gap-5 -mt-6 z-10">
                  <div className="flex flex-col gap-1.5 flex-1 min-w-0">
                    <h3
                      className="font-headline-md text-base sm:text-lg xl:text-xl font-bold text-[#e3e2e8] whitespace-nowrap overflow-hidden text-ellipsis tracking-tight"
                      title={founder.name}
                    >
                      {founder.name}
                    </h3>
                    <span className="font-label-technical text-xs text-primary font-semibold uppercase tracking-wider">
                      {founder.role}
                    </span>

                    {/* Social links row: only render icons if the link exists */}
                    {hasSocials && (
                      <div
                        className="flex items-center gap-2 mt-2"
                        role="list"
                        aria-label={t(
                          "landing.founders.social.listLabel",
                          { name: founder.name },
                          `Redes sociales de ${founder.name}`
                        )}
                      >
                        {founder.socials?.linkedin && (
                          <a
                            href={founder.socials.linkedin}
                            target="_blank"
                            rel="noreferrer noopener"
                            aria-label={t(
                              "landing.founders.social.linkedin",
                              { name: founder.name },
                              `Perfil de LinkedIn de ${founder.name}`
                            )}
                            title={t("landing.founders.social.titleLinkedin", "LinkedIn")}
                            className="size-8 rounded-lg bg-white/[0.04] hover:bg-primary/20 text-[#bcc9c7] hover:text-primary border border-white/10 hover:border-primary/40 flex items-center justify-center transition-all duration-200 hover:scale-110 active:scale-95 focus:outline-none focus:ring-2 focus:ring-primary/50"
                          >
                            <LinkedInIcon className="size-4" fill="currentColor" />
                          </a>
                        )}

                        {founder.socials?.github && (
                          <a
                            href={founder.socials.github}
                            target="_blank"
                            rel="noreferrer noopener"
                            aria-label={t(
                              "landing.founders.social.github",
                              { name: founder.name },
                              `Perfil de GitHub de ${founder.name}`
                            )}
                            title={t("landing.founders.social.titleGithub", "GitHub")}
                            className="size-8 rounded-lg bg-white/[0.04] hover:bg-primary/20 text-[#bcc9c7] hover:text-primary border border-white/10 hover:border-primary/40 flex items-center justify-center transition-all duration-200 hover:scale-110 active:scale-95 focus:outline-none focus:ring-2 focus:ring-primary/50"
                          >
                            <GitHubIcon className="size-4" />
                          </a>
                        )}

                        {founder.socials?.website && (
                          <a
                            href={founder.socials.website}
                            target="_blank"
                            rel="noreferrer noopener"
                            aria-label={t(
                              "landing.founders.social.website",
                              { name: founder.name },
                              `Portafolio web de ${founder.name}`
                            )}
                            title={t(
                              "landing.founders.social.titleWebsite",
                              "Portafolio / Web"
                            )}
                            className="size-8 rounded-lg bg-white/[0.04] hover:bg-primary/20 text-[#bcc9c7] hover:text-primary border border-white/10 hover:border-primary/40 flex items-center justify-center transition-all duration-200 hover:scale-110 active:scale-95 focus:outline-none focus:ring-2 focus:ring-primary/50"
                          >
                            <Globe className="size-4" aria-hidden="true" />
                          </a>
                        )}
                      </div>
                    )}

                    <p className="font-body-sm text-xs text-[#bcc9c7] mt-3 leading-relaxed flex-1">
                      {founder.bio}
                    </p>
                  </div>

                  <div
                    className={`mt-auto p-4 rounded-xl bg-[#292a2e]/80 border-l-2 ${founder.quoteBorder} shadow-inner`}
                  >
                    <p className="font-body-md text-xs italic text-[#e3e2e8]">
                      {founder.quote}
                    </p>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
