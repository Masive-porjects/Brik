import type { Metadata, Viewport } from "next";
import { I18nProvider } from "@/i18n/I18nContext";
import { AuthProvider } from "@/features/auth";
import { MasteringProvider } from "@/features/mastering";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brik — AI Mastering Studio",
  description: "Professional audio mastering powered by AI",
  icons: {
    icon: "/brand/mascota-3d.png",
    apple: "/brand/mascota-3d.png",
  },
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
