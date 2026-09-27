"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { User as UserIcon, LogOut, ChevronDown, ShieldCheck, Mail, ArrowLeft, Music2 } from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { useTranslation } from "@/i18n/useTranslation";
import { GoogleIcon, SpotifyIcon, DiscordIcon, GitHubIcon } from "./SocialIcons";
import { useIsMounted } from "@/shared/hooks";

interface UserMenuProps {
  onOpenLibrary?: () => void;
}

function getProviderMeta(providerRaw?: string, t?: (key: string, fallback: string) => string) {
  const provider = (providerRaw || "email").toLowerCase();
  if (provider.includes("google")) {
    return {
      id: "google",
      name: t ? t("auth.providerGoogle", "Google") : "Google",
      icon: <GoogleIcon className="size-3.5 shrink-0" />,
      badgeColor: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    };
  }
  if (provider.includes("spotify")) {
    return {
      id: "spotify",
      name: t ? t("auth.providerSpotify", "Spotify") : "Spotify",
      icon: <SpotifyIcon className="size-3.5 shrink-0" />,
      badgeColor: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    };
  }
  if (provider.includes("discord")) {
    return {
      id: "discord",
      name: t ? t("auth.providerDiscord", "Discord") : "Discord",
      icon: <DiscordIcon className="size-3.5 shrink-0" />,
      badgeColor: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
    };
  }
  if (provider.includes("github")) {
    return {
      id: "github",
      name: t ? t("auth.providerGithub", "GitHub") : "GitHub",
      icon: <GitHubIcon className="size-3.5 shrink-0" />,
      badgeColor: "bg-neutral-500/10 text-neutral-300 border-neutral-500/20",
    };
  }
  return {
    id: "email",
    name: t ? t("auth.providerEmail", "Correo electrónico") : "Email",
    icon: <Mail size={13} className="shrink-0 text-[var(--accent-primary)]" />,
    badgeColor: "bg-[var(--accent-primary)]/10 text-[var(--accent-primary)] border-[var(--accent-primary)]/20",
  };
}

function getActiveProvider(user: any): string {
  if (typeof window !== "undefined") {
    try {
      const stored = localStorage.getItem("waveia_last_auth_provider");
      if (stored) return stored;
    } catch {
      // Ignore
    }
  }

  if (user?.identities && Array.isArray(user.identities) && user.identities.length > 0) {
    const sorted = [...user.identities].sort((a: any, b: any) => {
      const timeA = new Date(a.last_sign_in_at || a.created_at || 0).getTime();
      const timeB = new Date(b.last_sign_in_at || b.created_at || 0).getTime();
      return timeB - timeA;
    });
    if (sorted[0]?.provider) {
      return sorted[0].provider;
    }
  }

  return user?.app_metadata?.provider || "email";
}

export default function UserMenu({ onOpenLibrary }: UserMenuProps = {}) {
  const pathname = usePathname();
  const isInAdmin = pathname?.startsWith("/admin");
  const { user, profile, isAdmin, isLoading, isSigningOut, signOut } = useAuth();
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const isMounted = useIsMounted();

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (!isMounted || isLoading) {
    return (
      <div className="size-8 rounded-full animate-pulse bg-[var(--surface-hover)] border border-[var(--border-subtle)]" />
    );
  }

  if (!user) {
    if (isSigningOut) {
      return null;
    }
    return (
      <Link
        href="/login"
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-full border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] hover:border-[var(--accent-primary)] text-[var(--text-primary)] transition-all shadow-sm"
      >
        <UserIcon size={14} className="text-[var(--accent-primary)]" />
        <span>{t("auth.signIn", "Iniciar sesión")}</span>
      </Link>
    );
  }

  const userEmail =
    user.email ||
    profile?.email ||
    user.user_metadata?.email ||
    user.identities?.find((i: any) => i.identity_data?.email)?.identity_data?.email ||
    "";

  const displayName =
    profile?.display_name ||
    user.user_metadata?.full_name ||
    user.user_metadata?.name ||
    userEmail.split("@")[0] ||
    "Producer";
  const userInitial = displayName.charAt(0).toUpperCase();

  const rawProvider = getActiveProvider(user);
  const providerMeta = getProviderMeta(rawProvider, t);

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-haspopup="true"
        className={`flex items-center gap-2 p-1 pl-1.5 pr-2.5 rounded-full border bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] transition-all text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)] ${
          isAdmin
            ? "border-amber-500/40 hover:border-amber-500/60 shadow-[0_0_12px_rgba(245,158,11,0.15)]"
            : "border-[var(--border-subtle)] hover:border-[var(--border-strong)]"
        }`}
      >
        <div className="relative shrink-0">
          <div
            className={`size-7 rounded-full flex items-center justify-center text-xs font-bold ${
              isAdmin
                ? "bg-amber-500/20 border border-amber-500/40 text-amber-400"
                : "bg-[var(--accent-primary)]/20 border border-[var(--accent-primary)]/40 text-[var(--accent-primary)]"
            }`}
          >
            {userInitial}
          </div>
          <span
            title={`${t("auth.accessMethod", "Método de acceso")}: ${providerMeta.name}`}
            className="absolute -bottom-0.5 -right-0.5 size-3.5 rounded-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] flex items-center justify-center shadow-xs overflow-hidden p-0.5"
          >
            {providerMeta.icon}
          </span>
        </div>
        <div className="flex items-center">
          <span className="hidden sm:inline-block text-xs font-medium max-w-[110px] truncate">
            {displayName}
          </span>
        </div>
        <ChevronDown
          size={13}
          className={`text-[var(--text-muted)] transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-2 w-68 rounded-2xl border p-2 shadow-2xl z-50 animate-in fade-in slide-in-from-top-2 duration-150 backdrop-blur-3xl"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border-strong)",
            boxShadow: "0 22px 55px -10px rgba(0, 0, 0, 0.75), 0 0 0 1px var(--border-strong), inset 0 1px 0 rgba(255, 255, 255, 0.08)",
          }}
        >
          <div className="px-3 py-2.5 border-b border-[var(--border-subtle)] mb-1">
            <div className="flex items-center justify-between gap-2 mb-1">
              <p className="text-xs font-semibold text-[var(--text-primary)] truncate">
                {displayName}
              </p>
              <div className="flex items-center gap-1 shrink-0">
                <span
                  title={providerMeta.name}
                  className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-[9px] font-semibold ${providerMeta.badgeColor}`}
                >
                  {providerMeta.icon}
                  <span>{providerMeta.name}</span>
                </span>
                <span
                  className={`text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full border ${
                    isAdmin
                      ? "bg-amber-500/15 border-amber-500/40 text-amber-400"
                      : "bg-[var(--accent-primary)]/15 border-[var(--accent-primary)]/30 text-[var(--accent-primary)]"
                  }`}
                >
                  {isAdmin ? t("auth.roleAdmin", "Admin") : t("auth.roleUser", "Usuario")}
                </span>
              </div>
            </div>
            <p className="text-[11px] text-[var(--text-secondary)] truncate">{userEmail || user.email}</p>
          </div>

          <div className="space-y-0.5">
            {isAdmin && (
              isInAdmin ? (
                <Link
                  href="/"
                  onClick={() => setIsOpen(false)}
                  className="flex items-center gap-2 px-3 py-2 text-xs rounded-xl hover:bg-[var(--accent-primary)]/15 text-[var(--accent-primary)] hover:brightness-110 transition-colors font-medium"
                >
                  <ArrowLeft size={14} className="text-[var(--accent-primary)]" />
                  <span>{t("admin.backToStudio", "Volver al Studio")}</span>
                </Link>
              ) : (
                <Link
                  href="/admin"
                  onClick={() => setIsOpen(false)}
                  className="flex items-center gap-2 px-3 py-2 text-xs rounded-xl hover:bg-amber-500/10 text-amber-400 hover:text-amber-300 transition-colors font-medium"
                >
                  <ShieldCheck size={14} className="text-amber-400" />
                  <span>{t("admin.menuLink", "Panel de Administración")}</span>
                </Link>
              )
            )}

            {onOpenLibrary && (
              <button
                type="button"
                onClick={() => {
                  setIsOpen(false);
                  onOpenLibrary();
                }}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs rounded-xl hover:bg-[var(--surface-hover)] text-[var(--text-primary)] transition-colors text-left cursor-pointer font-medium"
              >
                <Music2 size={14} className="text-[var(--accent-primary)]" />
                <span>{t("nav.myTracks", "Mis Canciones")}</span>
              </button>
            )}

            <button
              type="button"
              onClick={async () => {
                setIsOpen(false);
                if (typeof window !== "undefined") {
                  try {
                    localStorage.removeItem("waveia_last_auth_provider");
                  } catch {}
                }
                await signOut();
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs rounded-xl hover:bg-red-500/10 text-red-400 hover:text-red-300 transition-colors text-left cursor-pointer"
            >
              <LogOut size={14} />
              <span>{t("auth.signOut", "Cerrar sesión")}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
