import Link from "next/link";
import LanguageSwitcher from "@/presentation/components/LanguageSwitcher";
import ThemeToggle from "@/presentation/components/ThemeToggle";
import FloatingGhosts from "@/components/FloatingGhosts";
import FloatingNotes from "@/components/FloatingNotes";
import BigGhostWithNotes from "@/components/BigGhostWithNotes";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative h-screen max-h-screen flex flex-col justify-between bg-[var(--bg-app)] text-[var(--text-primary)] overflow-hidden select-none">
      {/* Crystal atmosphere — soft radial accents over base like LicenseGuard */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: `
            radial-gradient(ellipse 70% 55% at 18% 12%, rgba(98, 126, 132, 0.18), transparent 62%),
            radial-gradient(ellipse 60% 50% at 88% 82%, rgba(130, 156, 161, 0.16), transparent 65%),
            radial-gradient(ellipse 45% 40% at 68% 8%, rgba(98, 126, 132, 0.12), transparent 60%)
          `,
        }}
        aria-hidden="true"
      />

      {/* Floating ambient ghosts and musical notes */}
      <FloatingGhosts />
      <FloatingNotes />

      {/* Top Navigation */}
      <header className="relative z-30 shrink-0 flex items-center justify-between px-6 py-2.5">
        <Link
          href="/"
          className="rounded-full px-3.5 py-1.5 glass hover:border-[var(--accent-primary)] transition-colors group flex items-center gap-1 shadow-sm"
        >
          <span className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">
            Wave<span className="text-[var(--accent-primary)]">IA</span>
          </span>
        </Link>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          <LanguageSwitcher />
        </div>
      </header>

      {/* Main Form Container with Ghost leaning over */}
      <main className="relative z-20 flex-1 flex flex-col items-center justify-center px-4 py-1 sm:px-6 min-h-0 overflow-hidden">
        <div className="flex flex-col items-center w-full max-w-[400px]">
          <BigGhostWithNotes
            size={95}
            radius={75}
            noteCount={5}
            className="relative -mb-6 pointer-events-none select-none shrink-0"
            style={{
              opacity: 0.9,
              zIndex: 30,
              transform: "rotate(6deg)",
            }}
          />
          <div className="w-full relative z-20">{children}</div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-20 shrink-0 py-2 text-center text-[11px] text-[var(--text-muted)]">
        &copy; {new Date().getFullYear()} WaveIA Studio &bull; Next-Gen Audio Engine
      </footer>
    </div>
  );
}
