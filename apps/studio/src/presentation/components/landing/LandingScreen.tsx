"use client";

import FloatingGhosts from "@/presentation/components/FloatingGhosts";
import LandingScrollToTop from "./LandingScrollToTop";
import LandingHeader from "./LandingHeader";
import HeroGSAP from "./HeroGSAP";
import LandingPhilosophy from "./LandingPhilosophy";
import LandingABPlayer from "./LandingABPlayer";
import LandingDSPChain from "./LandingDSPChain";
import LandingEngineSpecs from "./LandingEngineSpecs";
import LandingPresets from "./LandingPresets";
import LandingPricing from "./LandingPricing";
import LandingFounders from "./LandingFounders";
import LandingFAQ from "./LandingFAQ";
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
        <HeroGSAP />
        <LandingPhilosophy />
        <LandingABPlayer />
        <LandingDSPChain />
        <LandingEngineSpecs />
        <LandingPresets />
        <LandingPricing />
        <LandingFounders />
        <LandingFAQ />
        <LandingCTA />
      </main>

      {/* Global Landing Footer */}
      <LandingFooter />

      {/* Floating Back to Top Ghost Button */}
      <LandingScrollToTop />
    </div>
  );
}
