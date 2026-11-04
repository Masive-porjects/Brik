"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Music4 } from "lucide-react";
import { useCallback, useState } from "react";

import DropZone from "@/presentation/components/DropZone";
import ChatPanel, {
  NEUTRAL_PROFILE,
  type Profile,
} from "@/presentation/components/chat/ChatPanel";
import { speak } from "@/lib/voice/speak";
import { VIEW_TRANSITION } from "@/shared/motion";

/**
 * Flujo de intención: subir el track y después contarle al agente cómo quieres
 * que suene.
 *
 * Son dos pasos y no uno solo a propósito: el agente calibra las magnitudes con
 * el análisis del track (género, loudness, rango dinámico), así que preguntar
 * antes de tener el audio lo obliga a responder a ciegas.
 */

type Step = "upload" | "chat";

function bienvenida(fileName: string): string {
  const name = fileName.replace(/\.[^.]+$/, "");
  return `Escuché "${name}". Cuéntame cómo quieres que suene: ¿más cálida, con más pegada, la voz al frente? Dilo con tus palabras, yo lo traduzco.`;
}

export default function VozPage() {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [profile, setProfile] = useState<Profile>(NEUTRAL_PROFILE);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback((selected: File) => {
    setFile(selected);
    setError(null);
    setStep("chat");
    // El drop cuenta como gesto del usuario, así que el navegador suele dejar
    // sonar esto. Si igual lo bloquea, speak() falla en silencio y el saludo
    // queda solo en texto: no vale la pena romper el flujo por eso.
    void speak(bienvenida(selected.name));
  }, []);

  return (
    <main className="mx-auto flex h-[100dvh] min-h-0 max-w-xl flex-col overflow-hidden p-4 sm:p-8">
      <AnimatePresence mode="wait">
        {step === "upload" ? (
          <motion.div key="upload" {...VIEW_TRANSITION} className="m-auto w-full">
            <header className="mb-6 text-center">
              <h1
                className="text-2xl font-medium tracking-tight"
                style={{ color: "var(--text-primary)" }}
              >
                Empecemos por tu <span className="serif-accent">track</span>
              </h1>
              <p className="mt-1.5 text-sm" style={{ color: "var(--text-muted)" }}>
                Carga el audio y después me cuentas cómo quieres que suene.
              </p>
            </header>

            <DropZone
              onFileSelected={handleFile}
              onError={(title, message) => setError(`${title}: ${message}`)}
            />

            {error && (
              <p className="mt-3 text-center text-xs" style={{ color: "var(--accent-error)" }}>
                {error}
              </p>
            )}
          </motion.div>
        ) : (
          <motion.div key="chat" {...VIEW_TRANSITION} className="flex min-h-0 flex-1 flex-col gap-3">
            <button
              type="button"
              onClick={() => setStep("upload")}
              className="flex items-center gap-2 self-start rounded-full border px-3 py-1.5
                text-xs transition-colors duration-300 hover:border-[var(--border-hover)]"
              style={{
                background: "var(--surface-hover)",
                borderColor: "var(--border-subtle)",
                color: "var(--text-secondary)",
              }}
            >
              <Music4 size={13} strokeWidth={1.75} />
              <span className="max-w-[16rem] truncate">{file?.name}</span>
            </button>

            <div className="min-h-0 flex-1">
              <ChatPanel
                profile={profile}
                onProfileChange={setProfile}
                welcome={file ? bienvenida(file.name) : undefined}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
