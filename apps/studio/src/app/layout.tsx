import type { Metadata, Viewport } from "next";
import {
  Syne,
  Plus_Jakarta_Sans,
  JetBrains_Mono,
  Instrument_Serif,
} from "next/font/google";
import { I18nProvider } from "@/i18n/I18nContext";
import { AuthProvider } from "@/features/auth";
import { MasteringProvider } from "@/features/mastering";
import "./globals.css";

/**
 * Self-hosted variable fonts via next/font/google (no runtime Google Fonts
 * requests). The `variable` names are the loader's internal CSS variables
 * (`--font-*-loaded`); the design-system tokens in globals.css `@theme` point
 * at them with literal fallback stacks (no circular var() references).
 */
const syne = Syne({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-syne-loaded",
});

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jakarta-loaded",
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono-loaded",
});

/**
 * Instrument Serif is a static (non-variable) face already used by the
 * `.serif-accent` utility across the app (voz, upload, chat, stem splitter,
 * mastering canvas). It must stay self-hosted now that the Google Fonts
 * @import was removed, or those screens silently fall back to Georgia.
 */
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-instrument-serif-loaded",
});

const siteTitle =
  "BrikMaster | IA + Motor DSP Determinista de Mezcla y Masterización";

const siteDescription =
  "Masteriza y mezcla tu música con IA y un motor DSP 100% determinista: análisis espectral, 13 etapas de procesamiento, salida 24-bit/48kHz y preservación de fase. Sin alucinaciones: el mismo archivo produce el mismo master, toma a toma.";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://brikmaster.app"
  ),
  title: {
    default: siteTitle,
    template: "%s | BrikMaster",
  },
  description: siteDescription,
  keywords: [
    "masterización con IA",
    "masterización online",
    "motor DSP determinista",
    "audio 24-bit 48kHz",
    "preservación de fase",
    "mastering espectral",
    "BrikMaster",
  ],
  openGraph: {
    title: siteTitle,
    description: siteDescription,
    type: "website",
    locale: "es_ES",
    images: [
      {
        url: "/brand/mascota-3d.png",
        width: 1024,
        height: 1024,
        alt: "BrikMaster",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
    images: ["/brand/mascota-3d.png"],
  },
  icons: {
    icon: "/brand/mascota-3d.png",
    apple: "/brand/mascota-3d.png",
  },
};

/** Schema.org structured data for search engines (landing <head>). */
const applicationLdJson = JSON.stringify({
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "BrikMaster",
  applicationCategory: "MultimediaApplication",
  operatingSystem: "Web",
  description: siteDescription,
  featureList: [
    "Masterización y mezcla con IA y un motor DSP 100% determinista",
    "Audio de alta resolución: 24-bit / 48kHz",
    "Preservación de fase en toda la cadena de procesamiento",
    "Cero alucinaciones: el mismo archivo de entrada produce el mismo master",
  ],
});

export const dynamic = "force-dynamic";

/**
 * iOS viewport config: allows fullscreen PWA-like behavior
 * without browser chrome overriding the layout.
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  themeColor: "#0b0b0c",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // The next/font `.variable` classes MUST live on <html> (:root). Tailwind v4
  // emits the `@theme` font tokens (--font-*, which reference --font-*-loaded)
  // on :root; if the loader variables are only defined on <body>, the var()
  // reference resolves as invalid at :root and every family silently falls
  // back to the UA system stack.
  return (
    <html
      lang="es"
      suppressHydrationWarning
      className={`${syne.variable} ${plusJakartaSans.variable} ${jetBrainsMono.variable} ${instrumentSerif.variable}`}
    >
      <head>
        {/* Theme initialization - runs before hydration */}
        <script
          id="theme-init"
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("waveai-theme");if(t==="light"){document.documentElement.dataset.theme="light";}}catch(e){}})();`,
          }}
        />
        {/* Viewport height fix - runs before hydration */}
        <script
          id="vh-fix"
          dangerouslySetInnerHTML={{
            __html: `(function(){function setVH(){var vh=window.innerHeight*0.01;document.documentElement.style.setProperty('--vh',vh+'px');}setVH();window.addEventListener('resize',setVH);})();`,
          }}
        />
        {/* Schema.org structured data - SoftwareApplication (printed as-is) */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: applicationLdJson }}
        />
      </head>
      <body className="antialiased min-h-screen">
        <I18nProvider>
          <AuthProvider>
            <MasteringProvider>{children}</MasteringProvider>
          </AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
