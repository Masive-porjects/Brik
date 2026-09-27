import { createClient } from "@/lib/supabase/client";
import type { AdminUser, RoleAuditLog, RoleUpdateResult } from "../types";

export interface FetchUsersOptions {
  page?: number;
  pageSize?: number;
  search?: string;
  role?: string;
}

export interface FetchUsersResult {
  users: AdminUser[];
  totalCount: number;
}

export interface FetchAuditLogsOptions {
  page?: number;
  pageSize?: number;
}

export interface FetchAuditLogsResult {
  logs: RoleAuditLog[];
  totalCount: number;
}

export interface AdminStats {
  total: number;
  admins: number;
  users: number;
}

/**
 * Scalable paginated user query leveraging Supabase .range() and exact row count.
 */
export async function fetchAdminUsers(
  options?: FetchUsersOptions
): Promise<FetchUsersResult> {
  const supabase = createClient();
  const page = Math.max(1, options?.page ?? 1);
  const pageSize = Math.max(1, options?.pageSize ?? 10);
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;

  let query = supabase
    .from("profiles")
    .select("*", { count: "exact" })
    .order("created_at", { ascending: false });

  if (options?.role && options.role !== "all") {
    query = query.eq("role", options.role);
  }

  if (options?.search && options.search.trim()) {
    const s = options.search.trim();
    query = query.or(`display_name.ilike.%${s}%,email.ilike.%${s}%`);
  }

  const { data, count, error } = await query.range(from, to);

  if (error) {
    throw new Error(error.message);
  }

  return {
    users: (data || []) as AdminUser[],
    totalCount: count ?? 0,
  };
}

/**
 * Efficient head queries to fetch global metrics without data payload.
 */
export async function fetchAdminStats(): Promise<AdminStats> {
  const supabase = createClient();
  try {
    const [totalRes, adminRes] = await Promise.all([
      supabase.from("profiles").select("*", { count: "exact", head: true }),
      supabase
        .from("profiles")
        .select("*", { count: "exact", head: true })
        .eq("role", "admin"),
    ]);

    const total = totalRes.count ?? 0;
    const admins = adminRes.count ?? 0;
    const users = Math.max(0, total - admins);

    return { total, admins, users };
  } catch {
    return { total: 0, admins: 0, users: 0 };
  }
}

export async function updateUserRole(
  targetUserId: string,
  newRole: string
): Promise<RoleUpdateResult> {
  const supabase = createClient();
  const { data, error } = await supabase.rpc("update_user_role", {
    target_user_id: targetUserId,
    new_role: newRole,
  });

  if (error) {
    throw new Error(error.message);
  }

  return data as RoleUpdateResult;
}

/**
 * Scalable paginated audit logs query using range and exact count.
 */
export async function fetchRoleAuditLogs(
  options?: FetchAuditLogsOptions
): Promise<FetchAuditLogsResult> {
  const supabase = createClient();
  const page = Math.max(1, options?.page ?? 1);
  const pageSize = Math.max(1, options?.pageSize ?? 10);
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;

  // Primary: direct table with exact range & count for scalable pagination
  const { data, count, error } = await supabase
    .from("role_audit_logs")
    .select("*", { count: "exact" })
    .order("created_at", { ascending: false })
    .range(from, to);

  if (!error && data) {
    return {
      logs: data as RoleAuditLog[],
      totalCount: count ?? 0,
    };
  }

  // Fallback RPC if table direct query is restricted
  try {
    const { data: rpcData, error: rpcError } = await supabase.rpc(
      "get_role_audit_history"
    );
    if (!rpcError && rpcData) {
      const allLogs = rpcData as RoleAuditLog[];
      return {
        logs: allLogs.slice(from, to + 1),
        totalCount: allLogs.length,
      };
    }
  } catch {
    // Ignore fallback RPC error
  }

  return {
    logs: [],
    totalCount: 0,
  };
}
