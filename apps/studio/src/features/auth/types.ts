import type { User } from "@supabase/supabase-js";

export type UserRole = "user" | "admin";

export interface UserProfile {
  id: string;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  role: UserRole;
  created_at?: string;
  updated_at?: string;
}

export interface AuthContextType {
  user: User | null;
  profile: UserProfile | null;
  role: UserRole;
  isAdmin: boolean;
  isLoading: boolean;
  isSigningOut: boolean;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}
