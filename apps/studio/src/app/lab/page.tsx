import InteractiveSequencer from "@/components/audio/InteractiveSequencer";

export default function LabPage() {
  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-4 px-4 py-10">
      <p className="text-xs tracking-wide text-[var(--text-muted)]">
        Laboratorio de audio — motor interactivo aislado del flujo de
        masterización
      </p>
      <InteractiveSequencer />
    </main>
  );
}
