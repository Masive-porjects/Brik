import type { Metadata } from "next";
import { LandingScreen } from "@/presentation/components/landing";

export const metadata: Metadata = {
  title: "WaveIA — AI Mastering Studio | Precisión Espectral 8x",
  description:
    "Estudio de masterización espectral con Inteligencia Artificial y cadena DSP de 13 etapas en tiempo real con 8x oversampling.",
};

export default function HomePage() {
  return <LandingScreen />;
}

