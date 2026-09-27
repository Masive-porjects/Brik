import type { UserRole } from "@/features/auth/types";

export interface AdminUser {
  id: string;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  role: UserRole;
  created_at: string;
  updated_at?: string;
}

export interface RoleAuditLog {
  id: string;
  target_user_id: string;
  target_email: string | null;
  target_display_name: string | null;
  changed_by_user_id: string;
  changed_by_email: string | null;
  changed_by_display_name: string | null;
  old_role: UserRole;
  new_role: UserRole;
  created_at: string;
}

export interface RoleUpdateResult {
  success: boolean;
  message?: string;
  target_user_id?: string;
  old_role?: string;
  new_role?: string;
}
