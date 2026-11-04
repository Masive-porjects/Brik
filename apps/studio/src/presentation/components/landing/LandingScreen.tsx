"use client";

import LandingScrollToTop from "./LandingScrollToTop";
import LandingHeader from "./LandingHeader";
import LandingHero from "./LandingHero";
import LandingBenefits from "./LandingBenefits";
import LandingBrikIA from "./LandingBrikIA";
import LandingABPlayer from "./LandingABPlayer";
import LandingPresets from "./LandingPresets";
import LandingPricing from "./LandingPricing";
import LandingFAQ from "./LandingFAQ";
import LandingFounders from "./LandingFounders";
import LandingFooter from "./LandingFooter";

export default function LandingScreen() {
  return (
    <div className="min-h-screen flex flex-col bg-[#0b0b0c] text-[#f4f4f2] font-sans selection:bg-primary-container selection:text-[var(--color-on-primary)] overflow-x-clip">
      <LandingHeader />

      <main className="flex-1 flex flex-col w-full">
        <LandingHero />
        <LandingBenefits />
        <LandingBrikIA />
        <LandingABPlayer />
        <LandingPresets />
        <LandingPricing />
        <LandingFAQ />
        <LandingFounders />
      </main>

      <LandingFooter />

      <LandingScrollToTop />
    </div>
  );
}
