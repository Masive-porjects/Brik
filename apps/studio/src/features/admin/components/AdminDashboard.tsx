"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Users,
  ShieldCheck,
  History,
  Search,
  RefreshCw,
  ArrowRight,
  ShieldAlert,
  AlertCircle,
  CheckCircle2,
  Lock,
  ArrowLeft,
  ChevronDown,
  Check,
} from "lucide-react";
import { useAuth } from "@/features/auth";
import { useTranslation } from "@/i18n/useTranslation";
import ThemeToggle from "@/presentation/components/ThemeToggle";
import LanguageSwitcher from "@/presentation/components/LanguageSwitcher";
import { UserMenu } from "@/features/auth";
import FloatingGhosts from "@/presentation/components/FloatingGhosts";
import FloatingNotes from "@/presentation/components/FloatingNotes";
import Pagination from "@/presentation/components/ui/Pagination";
import {
  fetchAdminUsers,
  fetchAdminStats,
  updateUserRole,
  fetchRoleAuditLogs,
} from "../services/adminService";
import type { AdminUser, RoleAuditLog } from "../types";

interface RoleSelectDropdownProps {
  user: AdminUser;
  onSelectRole: (u: AdminUser, newRole: string) => void;
  t: (key: string, fallback?: any) => string;
}

function RoleSelectDropdown({ user, onSelectRole, t }: RoleSelectDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen]);

  const isUserAdmin = user.role === "admin";

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer shadow-xs ${
          isUserAdmin
            ? "bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border-amber-500/30 hover:border-amber-500/50"
            : "bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border-[var(--border-subtle)] hover:border-[var(--accent-primary)]/40"
        }`}
      >
        {isUserAdmin ? (
          <ShieldCheck size={13} className="text-amber-400 shrink-0" />
        ) : (
          <Users size={13} className="text-[var(--accent-primary)] shrink-0" />
        )}
        <span className="capitalize">{isUserAdmin ? t("auth.roleAdmin", "Admin") : t("auth.roleUser", "Usuario")}</span>
        <ChevronDown
          size={12}
          className={`transition-transform duration-200 ${isOpen ? "rotate-180 text-[var(--text-primary)]" : "text-[var(--text-muted)]"}`}
        />
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-1.5 w-48 rounded-2xl border p-1.5 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-150 backdrop-blur-3xl"
          style={{
            backgroundColor: "var(--bg-elevated)",
            borderColor: "var(--border-strong)",
            boxShadow: "0 20px 45px -10px rgba(0, 0, 0, 0.75), 0 0 0 1px var(--border-strong), inset 0 1px 0 rgba(255, 255, 255, 0.08)",
          }}
        >
          <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] border-b border-[var(--border-subtle)] mb-1">
            {t("admin.selectRoleTitle", "Asignar Rol")}
          </div>

          <button
            type="button"
            onClick={() => {
              setIsOpen(false);
              if (user.role !== "user") {
                onSelectRole(user, "user");
              }
            }}
            className={`w-full flex items-center justify-between px-2.5 py-2 rounded-xl text-xs font-medium transition-all cursor-pointer ${
              user.role === "user"
                ? "bg-[var(--accent-primary)]/15 text-[var(--accent-primary)] font-semibold"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)]"
            }`}
          >
            <div className="flex items-center gap-2">
              <Users size={14} className={user.role === "user" ? "text-[var(--accent-primary)]" : "text-[var(--text-muted)]"} />
              <span>{t("auth.roleUser", "Usuario")}</span>
            </div>
            {user.role === "user" && <Check size={13} className="text-[var(--accent-primary)]" />}
          </button>

          <button
            type="button"
            onClick={() => {
              setIsOpen(false);
              if (user.role !== "admin") {
                onSelectRole(user, "admin");
              }
            }}
            className={`w-full flex items-center justify-between px-2.5 py-2 rounded-xl text-xs font-medium transition-all cursor-pointer ${
              user.role === "admin"
                ? "bg-amber-500/15 text-amber-400 font-semibold"
                : "text-[var(--text-secondary)] hover:text-amber-400 hover:bg-amber-500/10"
            }`}
          >
            <div className="flex items-center gap-2">
              <ShieldCheck size={14} className={user.role === "admin" ? "text-amber-400" : "text-[var(--text-muted)]"} />
              <span>{t("auth.roleAdmin", "Admin")}</span>
            </div>
            {user.role === "admin" && <Check size={13} className="text-amber-400" />}
          </button>
        </div>
      )}
    </div>
  );
}

export default function AdminDashboard() {
  const { user: currentUser, isAdmin, isLoading: authLoading, isSigningOut } = useAuth();
  const { t } = useTranslation();

  const [activeTab, setActiveTab] = useState<"users" | "audit">("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [totalUsersCount, setTotalUsersCount] = useState(0);
  const [stats, setStats] = useState({ total: 0, admins: 0, users: 0 });
  const [auditLogs, setAuditLogs] = useState<RoleAuditLog[]>([]);
  const [totalAuditCount, setTotalAuditCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);

  // Pagination states
  const [userPage, setUserPage] = useState(1);
  const [userPageSize, setUserPageSize] = useState(10);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(10);

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "admin" | "user">("all");

  // Debounce search input by 250ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
      setUserPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Role change confirmation modal state
  const [targetUser, setTargetUser] = useState<AdminUser | null>(null);
  const [selectedNewRole, setSelectedNewRole] = useState<string>("");
  const [submittingRole, setSubmittingRole] = useState(false);

  const loadUsersData = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const [usersRes, statsRes] = await Promise.all([
        fetchAdminUsers({
          page: userPage,
          pageSize: userPageSize,
          search: debouncedSearch,
          role: roleFilter,
        }),
        fetchAdminStats(),
      ]);
      setUsers(usersRes.users);
      setTotalUsersCount(usersRes.totalCount);
      setStats(statsRes);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("admin.loadError", "Error al cargar la información del panel.")
      );
    }
  }, [isAdmin, userPage, userPageSize, debouncedSearch, roleFilter, t]);

  const loadAuditData = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const auditRes = await fetchRoleAuditLogs({
        page: auditPage,
        pageSize: auditPageSize,
      });
      setAuditLogs(auditRes.logs);
      setTotalAuditCount(auditRes.totalCount);
    } catch {
      // Non blocking
    }
  }, [isAdmin, auditPage, auditPageSize]);

  // Initial and reactive load
  useEffect(() => {
    let isMounted = true;
    if (!authLoading && isAdmin) {
      setLoading(true);
      Promise.all([loadUsersData(), loadAuditData()]).finally(() => {
        if (isMounted) setLoading(false);
      });
    }
    return () => {
      isMounted = false;
    };
  }, [authLoading, isAdmin, loadUsersData, loadAuditData]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([loadUsersData(), loadAuditData()]);
    } finally {
      setLoading(false);
    }
  }, [loadUsersData, loadAuditData]);

  // Stats
  const totalUsers = stats.total;
  const adminCount = stats.admins;
  const regularCount = stats.users;
  const totalAuditEvents = totalAuditCount;

  const handleOpenRoleModal = (u: AdminUser, newRole: string) => {
    if (u.id === currentUser?.id) {
      setError(
        t(
          "admin.cantChangeOwnRole",
          "No puedes modificar tu propio rol. La reasignación debe ser realizada por otro administrador."
        )
      );
      return;
    }
    setTargetUser(u);
    setSelectedNewRole(newRole);
    setError(null);
  };

  const handleConfirmRoleChange = async () => {
    if (!targetUser || !selectedNewRole) return;
    setSubmittingRole(true);
    setError(null);
    setSuccessNotice(null);

    try {
      await updateUserRole(targetUser.id, selectedNewRole);
      setSuccessNotice(
        t(
          "admin.roleUpdatedSuccess",
          `Rol de ${targetUser.display_name || targetUser.email} actualizado a "${selectedNewRole}". Evento registrado en auditoría.`
        )
      );
      setTargetUser(null);
      await loadData();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("admin.roleUpdateFailed", "No se pudo actualizar el rol.")
      );
    } finally {
      setSubmittingRole(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-base)]">
        <div className="size-10 rounded-full animate-spin border-2 border-[var(--accent-primary)] border-t-transparent" />
      </div>
    );
  }

  if (!isAdmin && !isSigningOut) {
    return (
      <div className="relative min-h-screen bg-[var(--bg-app)] text-[var(--text-primary)] flex flex-col overflow-x-hidden">
        {/* Crystal atmosphere */}
        <div
          className="pointer-events-none fixed inset-0 z-0"
          style={{
            background: `
              radial-gradient(ellipse 70% 55% at 18% 12%, rgba(98, 126, 132, 0.18), transparent 62%),
              radial-gradient(ellipse 60% 50% at 88% 82%, rgba(130, 156, 161, 0.16), transparent 65%),
              radial-gradient(ellipse 45% 40% at 68% 8%, rgba(98, 126, 132, 0.12), transparent 60%)
            `,
          }}
          aria-hidden="true"
        />
        <FloatingGhosts />
        <FloatingNotes />

        {/* Top Header */}
        <header className="relative z-30 shrink-0 flex items-center justify-between px-4 sm:px-6 lg:px-8 py-3.5 border-b border-[var(--border-subtle)] backdrop-blur-xl bg-[var(--bg-app)]/70">
          <Link
            href="/"
            className="rounded-full px-4 py-2 glass hover:border-[var(--accent-primary)] transition-all flex items-center gap-1.5 shadow-sm"
          >
            <span className="text-base font-semibold tracking-tight text-[var(--text-primary)]">
              Wave<span className="text-[var(--accent-primary)]">IA</span>
            </span>
          </Link>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <LanguageSwitcher />
            <UserMenu />
          </div>
        </header>

        {/* Access denied body */}
        <main className="relative z-10 flex-1 flex items-center justify-center p-4">
          <div
            className="max-w-md w-full p-8 rounded-3xl border text-center backdrop-blur-2xl shadow-2xl"
            style={{
              background: "var(--bg-glass-elevated)",
              borderColor: "var(--border-strong)",
            }}
          >
            <div className="size-14 mx-auto mb-4 rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center text-red-400">
              <ShieldAlert size={28} />
            </div>
            <h2 className="text-xl font-bold text-[var(--text-primary)] mb-2">
              {t("admin.accessDeniedTitle", "Acceso Restringido")}
            </h2>
            <p className="text-sm text-[var(--text-secondary)] mb-6">
              {t(
                "admin.accessDeniedDesc",
                "Se requieren permisos de Administrador para acceder a este panel de control."
              )}
            </p>
            <Link
              href="/"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-xs text-[var(--bg-base)] bg-[var(--accent-primary)] hover:brightness-110 transition-all shadow-md"
            >
              <ArrowLeft size={16} />
              <span>{t("admin.backToStudio", "Volver al Studio")}</span>
            </Link>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen bg-[var(--bg-app)] text-[var(--text-primary)] flex flex-col overflow-x-hidden">
      {/* Crystal atmosphere & ambient floating elements */}
      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background: `
            radial-gradient(ellipse 70% 55% at 18% 12%, rgba(98, 126, 132, 0.18), transparent 62%),
            radial-gradient(ellipse 60% 50% at 88% 82%, rgba(130, 156, 161, 0.16), transparent 65%),
            radial-gradient(ellipse 45% 40% at 68% 8%, rgba(98, 126, 132, 0.12), transparent 60%)
          `,
        }}
        aria-hidden="true"
      />
      <FloatingGhosts />
      <FloatingNotes />

      {/* Top Header Navigation */}
      <header className="relative z-30 shrink-0 flex items-center justify-between px-4 sm:px-6 lg:px-8 py-3.5 border-b border-[var(--border-subtle)] backdrop-blur-xl bg-[var(--bg-app)]/70">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="rounded-full px-4 py-2 glass hover:border-[var(--accent-primary)] transition-all flex items-center gap-1.5 shadow-sm group"
          >
            <span className="text-base font-semibold tracking-tight text-[var(--text-primary)]">
              Wave<span className="text-[var(--accent-primary)]">IA</span>
            </span>
            <span className="hidden sm:inline-block text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 ml-1 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
              Admin
            </span>
          </Link>

          <Link
            href="/"
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] border border-transparent hover:border-[var(--border-subtle)] transition-all"
          >
            <ArrowLeft size={13} />
            <span>{t("admin.backToStudio", "Volver al Studio")}</span>
          </Link>
        </div>

        {/* Right tools: Theme, Language, UserMenu */}
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <LanguageSwitcher />
          <UserMenu />
        </div>
      </header>

      {/* Main Content Area with Entrance Animation */}
      <motion.main
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
        className="relative z-10 flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto space-y-6"
      >
        {/* Page Title & Actions */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[var(--border-subtle)]">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link
                href="/"
                className="sm:hidden text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1"
              >
                <ArrowLeft size={13} />
                <span>{t("admin.backToStudio", "Volver al Studio")}</span>
              </Link>
              <span className="sm:hidden text-[var(--border-strong)]">•</span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                WaveIA Control
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight flex items-center gap-2.5">
              <span>{t("admin.dashboardTitle", "Panel de Administración")}</span>
              <ShieldCheck size={26} className="text-amber-400" />
            </h1>
            <p className="text-xs sm:text-sm text-[var(--text-secondary)] mt-1">
              {t(
                "admin.dashboardSubtitle",
                "Gestión de usuarios, asignación de roles y trazabilidad de eventos"
              )}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] hover:border-[var(--accent-primary)] text-[var(--text-primary)] transition-all cursor-pointer disabled:opacity-50 shadow-sm"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              <span>{t("admin.refresh", "Actualizar")}</span>
            </button>
          </div>
        </div>

        {/* Global Feedback Notices */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -5 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-3.5 rounded-2xl border border-red-500/30 bg-red-500/10 text-red-400 text-xs flex items-center gap-2.5 shadow-sm"
          >
            <AlertCircle size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
            <button
              onClick={() => setError(null)}
              className="text-xs text-red-300 hover:underline ml-2"
            >
              ✕
            </button>
          </motion.div>
        )}

        {successNotice && (
          <motion.div
            initial={{ opacity: 0, y: -5 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-3.5 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs flex items-center gap-2.5 shadow-sm"
          >
            <CheckCircle2 size={16} className="shrink-0" />
            <span className="flex-1">{successNotice}</span>
            <button
              onClick={() => setSuccessNotice(null)}
              className="text-xs text-emerald-300 hover:underline ml-2"
            >
              ✕
            </button>
          </motion.div>
        )}

        {/* Stats Grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <div
            className="p-4 rounded-2xl border backdrop-blur-xl"
            style={{
              background: "var(--bg-glass-elevated)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <div className="flex items-center justify-between text-[var(--text-muted)] mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">
                {t("admin.statTotalUsers", "Total Usuarios")}
              </span>
              <Users size={16} />
            </div>
            <p className="text-2xl font-black text-[var(--text-primary)]">{totalUsers}</p>
          </div>

          <div
            className="p-4 rounded-2xl border backdrop-blur-xl"
            style={{
              background: "var(--bg-glass-elevated)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <div className="flex items-center justify-between text-amber-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">
                {t("admin.statAdmins", "Administradores")}
              </span>
              <ShieldCheck size={16} />
            </div>
            <p className="text-2xl font-black text-amber-400">{adminCount}</p>
          </div>

          <div
            className="p-4 rounded-2xl border backdrop-blur-xl"
            style={{
              background: "var(--bg-glass-elevated)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <div className="flex items-center justify-between text-[var(--accent-primary)] mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">
                {t("admin.statRegularUsers", "Usuarios Estándar")}
              </span>
              <Users size={16} />
            </div>
            <p className="text-2xl font-black text-[var(--accent-primary)]">{regularCount}</p>
          </div>

          <div
            className="p-4 rounded-2xl border backdrop-blur-xl"
            style={{
              background: "var(--bg-glass-elevated)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <div className="flex items-center justify-between text-purple-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider">
                {t("admin.statAuditEvents", "Eventos de Rol")}
              </span>
              <History size={16} />
            </div>
            <p className="text-2xl font-black text-purple-400">{totalAuditEvents}</p>
          </div>
        </div>

        {/* Tab Selector */}
        <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] pb-2">
          <button
            type="button"
            onClick={() => setActiveTab("users")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all ${
              activeTab === "users"
                ? "bg-[var(--accent-primary)] text-[var(--bg-base)] shadow-md"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)]"
            }`}
          >
            <Users size={15} />
            <span>{t("admin.tabUsers", "Usuarios y Roles")}</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-black/20">
              {totalUsers}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("audit")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all ${
              activeTab === "audit"
                ? "bg-[var(--accent-primary)] text-[var(--bg-base)] shadow-md"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)]"
            }`}
          >
            <History size={15} />
            <span>{t("admin.tabAudit", "Historial de Auditoría")}</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-black/20">
              {totalAuditEvents}
            </span>
          </button>
        </div>

        {/* TAB 1: USERS & ROLES */}
        {activeTab === "users" && (
          <div className="space-y-4">
            {/* Filters bar */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
              <div className="relative flex-1 max-w-md">
                <Search
                  size={15}
                  className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
                />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t("admin.searchPlaceholder", "Buscar por nombre, correo o ID...")}
                  className="w-full pl-9 pr-4 py-2 text-xs rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-primary)] transition-all"
                />
              </div>

              <div className="flex items-center gap-1.5 text-xs">
                {(["all", "admin", "user"] as const).map((rf) => (
                  <button
                    key={rf}
                    onClick={() => {
                      setRoleFilter(rf);
                      setUserPage(1);
                    }}
                    className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                      roleFilter === rf
                        ? "bg-[var(--surface-active)] text-[var(--text-primary)] border border-[var(--accent-primary)]/40"
                        : "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]"
                    }`}
                  >
                    {rf === "all"
                      ? t("admin.filterAll", "Todos")
                      : rf === "admin"
                      ? t("admin.filterAdmin", "Admins")
                      : t("admin.filterUser", "Usuarios")}
                  </button>
                ))}
              </div>
            </div>

            {/* Users Table */}
            <div
              className="rounded-3xl border backdrop-blur-2xl shadow-xl"
              style={{
                background: "var(--bg-glass-elevated)",
                borderColor: "var(--border-strong)",
              }}
            >
              <div className="overflow-x-auto min-h-[260px] pb-8">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-[var(--border-subtle)] bg-[var(--surface-elevated)]/50 text-[var(--text-muted)] uppercase tracking-wider text-[10px]">
                    <tr>
                      <th className="py-3.5 px-4 sm:px-6">{t("admin.thUser", "Usuario")}</th>
                      <th className="py-3.5 px-4 hidden md:table-cell">
                        {t("admin.thEmail", "Correo")}
                      </th>
                      <th className="py-3.5 px-4 hidden lg:table-cell">
                        {t("admin.thCreated", "Fecha Registro")}
                      </th>
                      <th className="py-3.5 px-4">{t("admin.thRole", "Rol Actual")}</th>
                      <th className="py-3.5 px-4 sm:px-6 text-right">
                        {t("admin.thAction", "Acción de Rol")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {users.length === 0 ? (
                      <tr>
                        <td
                          colSpan={5}
                          className="py-12 text-center text-xs text-[var(--text-muted)]"
                        >
                          {t("admin.noUsersFound", "No se encontraron usuarios.")}
                        </td>
                      </tr>
                    ) : (
                      users.map((u) => {
                        const isSelf = u.id === currentUser?.id;
                        const initial = (u.display_name || u.email || "U")
                          .charAt(0)
                          .toUpperCase();
                        const isUserAdmin = u.role === "admin";

                        return (
                          <tr
                            key={u.id}
                            className="hover:bg-[var(--surface-hover)]/60 transition-colors"
                          >
                            <td className="py-3.5 px-4 sm:px-6">
                              <div className="flex items-center gap-3">
                                <div
                                  className={`size-8 rounded-full flex items-center justify-center font-bold text-xs shrink-0 ${
                                    isUserAdmin
                                      ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                                      : "bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] border border-[var(--accent-primary)]/40"
                                  }`}
                                >
                                  {initial}
                                </div>
                                <div className="min-w-0">
                                  <div className="flex items-center gap-1.5">
                                    <p className="font-semibold text-[var(--text-primary)] truncate max-w-[140px] sm:max-w-xs">
                                      {u.display_name || t("common.notIdentified", "Sin nombre")}
                                    </p>
                                    {isSelf && (
                                      <span className="px-1.5 py-0.2 rounded-full text-[9px] font-bold bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] border border-[var(--accent-primary)]/40">
                                        {t("admin.badgeYou", "Tú")}
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-[11px] text-[var(--text-muted)] truncate md:hidden">
                                    {u.email}
                                  </p>
                                </div>
                              </div>
                            </td>

                            <td className="py-3.5 px-4 hidden md:table-cell text-[var(--text-secondary)] font-mono text-[11px]">
                              {u.email}
                            </td>

                            <td className="py-3.5 px-4 hidden lg:table-cell text-[var(--text-muted)] text-[11px]">
                              {new Date(u.created_at).toLocaleDateString()}
                            </td>

                            <td className="py-3.5 px-4">
                              <span
                                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border ${
                                  isUserAdmin
                                    ? "bg-amber-500/15 border-amber-500/40 text-amber-400"
                                    : "bg-[var(--accent-primary)]/15 border-[var(--accent-primary)]/30 text-[var(--accent-primary)]"
                                }`}
                              >
                                {isUserAdmin ? (
                                  <ShieldCheck size={11} />
                                ) : (
                                  <Users size={11} />
                                )}
                                <span>{u.role}</span>
                              </span>
                            </td>

                            <td className="py-3.5 px-4 sm:px-6 text-right">
                              {isSelf ? (
                                <div
                                  className="inline-flex items-center gap-1 text-[10px] text-[var(--text-muted)] bg-[var(--surface-hover)] px-2.5 py-1 rounded-lg border border-[var(--border-subtle)] select-none"
                                  title={t(
                                    "admin.selfChangeLockNote",
                                    "No puedes cambiar tu propio rol"
                                  )}
                                >
                                  <Lock size={11} />
                                  <span>{t("admin.lockedSelf", "Bloqueado (Tú)")}</span>
                                </div>
                              ) : (
                                <RoleSelectDropdown
                                  user={u}
                                  onSelectRole={handleOpenRoleModal}
                                  t={t}
                                />
                              )}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              <Pagination
                page={userPage}
                pageSize={userPageSize}
                totalCount={totalUsersCount}
                pageSizeOptions={[10, 25, 50]}
                onPageChange={(p) => setUserPage(p)}
                onPageSizeChange={(sz) => {
                  setUserPageSize(sz);
                  setUserPage(1);
                }}
                isLoading={loading}
              />
            </div>
          </div>
        )}

        {/* TAB 2: AUDIT TRAIL */}
        {activeTab === "audit" && (
          <div className="space-y-4">
            <div
              className="rounded-3xl border overflow-hidden backdrop-blur-2xl shadow-xl p-4 sm:p-6"
              style={{
                background: "var(--bg-glass-elevated)",
                borderColor: "var(--border-strong)",
              }}
            >
              <div className="flex items-center justify-between pb-4 border-b border-[var(--border-subtle)] mb-4">
                <div>
                  <h3 className="text-base font-bold text-[var(--text-primary)]">
                    {t("admin.auditLogTitle", "Trazabilidad de Cambios de Rol")}
                  </h3>
                  <p className="text-xs text-[var(--text-muted)] mt-0.5">
                    {t(
                      "admin.auditLogSubtitle",
                      "Registro inmutable de quién modificó el rol de qué usuario y en qué fecha"
                    )}
                  </p>
                </div>
              </div>

              {auditLogs.length === 0 ? (
                <div className="py-12 text-center text-xs text-[var(--text-muted)]">
                  {t(
                    "admin.noAuditLogs",
                    "Aún no hay eventos registrados de reasignación de roles."
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  {auditLogs.map((log) => (
                    <div
                      key={log.id}
                      className="p-3.5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)]/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
                    >
                      <div className="flex items-start gap-3">
                        <div className="size-8 rounded-xl bg-purple-500/15 border border-purple-500/30 text-purple-400 flex items-center justify-center shrink-0 mt-0.5">
                          <History size={15} />
                        </div>
                        <div>
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-semibold text-[var(--text-primary)]">
                              {log.changed_by_display_name ||
                                log.changed_by_email ||
                                t("admin.adminUser", "Administrador")}
                            </span>
                            <span className="text-[var(--text-muted)]">
                              {t("admin.changedRoleOf", "cambió el rol de")}
                            </span>
                            <span className="font-semibold text-[var(--text-primary)]">
                              {log.target_display_name || log.target_email || log.target_user_id}
                            </span>
                          </div>

                          <div className="flex items-center gap-2 mt-1.5">
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-[var(--surface-hover)] border border-[var(--border-subtle)] text-[var(--text-muted)]">
                              {log.old_role}
                            </span>
                            <ArrowRight size={12} className="text-[var(--text-muted)]" />
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
                                log.new_role === "admin"
                                  ? "bg-amber-500/15 border-amber-500/40 text-amber-400"
                                  : "bg-[var(--accent-primary)]/15 border-[var(--accent-primary)]/40 text-[var(--accent-primary)]"
                              }`}
                            >
                              {log.new_role}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="text-[11px] text-[var(--text-muted)] sm:text-right shrink-0">
                        {new Date(log.created_at).toLocaleString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <Pagination
                page={auditPage}
                pageSize={auditPageSize}
                totalCount={totalAuditCount}
                pageSizeOptions={[10, 25, 50]}
                onPageChange={(p) => setAuditPage(p)}
                onPageSizeChange={(sz) => {
                  setAuditPageSize(sz);
                  setAuditPage(1);
                }}
                isLoading={loading}
              />
            </div>
          </div>
        )}

        {/* Confirmation Modal */}
        <AnimatePresence>
          {targetUser && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
              <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className="w-full max-w-md p-6 rounded-3xl border shadow-2xl backdrop-blur-2xl"
                style={{
                  backgroundColor: "var(--bg-elevated)",
                  borderColor: "var(--border-strong)",
                  boxShadow: "0 24px 60px -12px rgba(0, 0, 0, 0.8), 0 0 0 1px var(--border-strong)",
                }}
              >
                <div className="flex items-center gap-3 mb-4">
                  <div className="size-10 rounded-2xl bg-amber-500/15 border border-amber-500/30 text-amber-400 flex items-center justify-center shrink-0">
                    <ShieldCheck size={20} />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-[var(--text-primary)]">
                      {t("admin.confirmModalTitle", "¿Confirmar reasignación de rol?")}
                    </h3>
                    <p className="text-xs text-[var(--text-muted)]">
                      {t("admin.confirmModalSubtitle", "Esta acción creará un registro de auditoría")}
                    </p>
                  </div>
                </div>

                <div className="p-3.5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] space-y-2 mb-5 text-xs">
                  <div className="flex justify-between">
                    <span className="text-[var(--text-muted)]">{t("admin.thUser", "Usuario")}:</span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      {targetUser.display_name || targetUser.email}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-[var(--text-muted)]">{t("admin.changeSummary", "Cambio")}:</span>
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-[var(--surface-hover)] border border-[var(--border-subtle)] text-[var(--text-muted)]">
                        {targetUser.role}
                      </span>
                      <ArrowRight size={12} className="text-[var(--text-muted)]" />
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 border border-amber-500/40 text-amber-400 uppercase">
                        {selectedNewRole}
                      </span>
                    </div>
                  </div>
                  <div className="flex justify-between pt-1 border-t border-[var(--border-subtle)] text-[11px]">
                    <span className="text-[var(--text-muted)]">
                      {t("admin.performedBy", "Efectuado por")}:
                    </span>
                    <span className="font-medium text-[var(--text-secondary)] truncate max-w-[200px]">
                      {currentUser?.email}
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-end gap-2.5">
                  <button
                    type="button"
                    onClick={() => setTargetUser(null)}
                    disabled={submittingRole}
                    className="px-4 py-2 text-xs font-semibold rounded-xl border border-[var(--border-subtle)] hover:bg-[var(--surface-hover)] text-[var(--text-secondary)] transition-all cursor-pointer"
                  >
                    {t("common.cancel", "Cancelar")}
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmRoleChange}
                    disabled={submittingRole}
                    className="px-5 py-2 text-xs font-semibold rounded-xl text-[var(--bg-base)] bg-[var(--accent-primary)] hover:brightness-110 active:scale-[0.99] transition-all shadow-md cursor-pointer disabled:opacity-50"
                  >
                    {submittingRole
                      ? t("common.saving", "Guardando...")
                      : t("admin.confirmApply", "Confirmar y Registrar")}
                  </button>
                </div>
              </motion.div>
            </div>
          )}
        </AnimatePresence>
      </motion.main>
    </div>
  );
}
