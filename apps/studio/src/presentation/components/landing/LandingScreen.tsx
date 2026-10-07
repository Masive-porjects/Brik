"use client";

import FloatingGhosts from "@/presentation/components/FloatingGhosts";
import LandingScrollToTop from "./LandingScrollToTop";
import LandingHeader from "./LandingHeader";
import LandingHero from "./LandingHero";
import LandingPhilosophy from "./LandingPhilosophy";
import LandingABPlayer from "./LandingABPlayer";
import LandingDSPChain from "./LandingDSPChain";
import LandingPresets from "./LandingPresets";
import LandingFounders from "./LandingFounders";
import LandingCTA from "./LandingCTA";
import LandingFooter from "./LandingFooter";

export default function LandingScreen() {
  return (
    <div className="min-h-screen flex flex-col bg-[#121317] text-[#e3e2e8] font-sans relative selection:bg-primary-container selection:text-[#003734] overflow-x-clip overflow-y-auto">
      {/* Ambient decorative brand ghosts floating across the viewport */}
      <FloatingGhosts zIndex={1} />

      {/* Fixed/Sticky Top Navigation Header */}
      <LandingHeader />

      {/* Main Landing Sections Flow */}
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

      {/* Floating Back to Top Ghost Button */}
      <LandingScrollToTop />
    </div>
  );
}
