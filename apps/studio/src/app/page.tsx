"use client";

import {
  LandingHeader,
  LandingHero,
  LandingPhilosophy,
  LandingABPlayer,
  LandingDSPChain,
  LandingPresets,
  LandingFounders,
  LandingCTA,
  LandingFooter,
} from "@/presentation/components/landing";
import FloatingGhosts from "@/presentation/components/FloatingGhosts";

export default function HomePage() {
  return (
    <div className="min-h-screen flex flex-col bg-[#121317] text-[#e3e2e8] font-sans relative selection:bg-primary-container selection:text-[#003734]">
      {/* Ambient decorative brand ghosts floating across the viewport */}
      <FloatingGhosts zIndex={1} />

      {/* Top Navigation */}
      <LandingHeader />

      {/* Main Landing Sections */}
      <main className="flex-1 flex flex-col w-full relative z-10">
        <LandingHero />
        <LandingPhilosophy />
        <LandingABPlayer />
        <LandingDSPChain />
        <LandingPresets />
        <LandingFounders />
        <LandingCTA />
      </main>

      {/* Global Landing Footer */}
      <LandingFooter />
    </div>
  );
}
