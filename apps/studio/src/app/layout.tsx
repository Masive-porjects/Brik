import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { I18nProvider } from "@/i18n/I18nContext";
import { AuthProvider } from "@/features/auth";
import { MasteringProvider } from "@/features/mastering";
import "./globals.css";

export const metadata: Metadata = {
  title: "WaveIA — AI Mastering Studio",
  description: "Professional audio mastering powered by AI",
};

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
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased min-h-screen">
        <I18nProvider>
          <AuthProvider>
            <MasteringProvider>{children}</MasteringProvider>
          </AuthProvider>
        </I18nProvider>
        <Script id="theme-init" strategy="beforeInteractive">
          {`(function(){try{var t=localStorage.getItem("waveai-theme");if(t==="light"){document.documentElement.dataset.theme="light";}}catch(e){}})();`}
        </Script>
        <Script id="vh-fix" strategy="beforeInteractive">
          {`(function(){function setVH(){var vh=window.innerHeight*0.01;document.documentElement.style.setProperty('--vh',vh+'px');}setVH();window.addEventListener('resize',setVH);})();`}
        </Script>
      </body>
    </html>
  );
}
