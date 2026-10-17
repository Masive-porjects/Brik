import type { Metadata } from "next";
import { LandingScreen } from "@/presentation/components/landing";
import esDict from "@/i18n/locales/es.json";

// The landing is the canonical root; every other route declares its own
// canonical (or none), so this must NOT live in the root layout.
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

/**
 * FAQPage structured data built from the same i18n content the landing FAQ
 * renders (default locale `es`), so the markup always matches the questions
 * and answers a crawler can actually see on the page.
 */
const FAQ_KEYS = ["ip", "formats", "deterministic", "privacy", "skill"] as const;

const faqLdJson = JSON.stringify({
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: FAQ_KEYS.map((key) => ({
    "@type": "Question",
    name: esDict.landing.faq[key].question,
    acceptedAnswer: {
      "@type": "Answer",
      text: esDict.landing.faq[key].answer,
    },
  })),
});

export default function HomePage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: faqLdJson }}
      />
      <LandingScreen />
    </>
  );
}
