"use client";

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import type { User, AuthChangeEvent, Session } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import type { AuthContextType, UserProfile } from "../types";
import SignOutModal from "../components/SignOutModal";

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const supabase = createClient();

  const fetchProfile = useCallback(async (userId: string, currentUser?: User) => {
    try {
      const { data, error } = await supabase
        .from("profiles")
        .select("*")
        .eq("id", userId)
        .single();

      if (!error && data) {
        const resolvedEmail =
          data.email ||
          currentUser?.email ||
          (currentUser?.user_metadata?.email as string | undefined) ||
          (currentUser?.identities?.find((id) => id.identity_data?.email)?.identity_data?.email as string | undefined) ||
          null;

        setProfile({
          id: data.id,
          email: resolvedEmail,
          display_name: data.display_name,
          avatar_url: data.avatar_url,
          role: (data.role?.toLowerCase() as UserProfile["role"]) || "user",
          created_at: data.created_at,
          updated_at: data.updated_at,
        });

        // Self-heal: If profile in db had email null but we have resolvedEmail, update it!
        if (!data.email && resolvedEmail) {
          supabase
            .from("profiles")
            .update({ email: resolvedEmail })
            .eq("id", userId)
            .then(() => {});
        }
      } else {
        // Fallback to user metadata & self-heal by writing to public.profiles
        const fallbackDisplayName =
          currentUser?.user_metadata?.full_name ||
          currentUser?.user_metadata?.name ||
          currentUser?.email?.split("@")[0] ||
          "Producer";
        const fallbackAvatar =
          currentUser?.user_metadata?.avatar_url ||
          currentUser?.user_metadata?.picture ||
          null;
        const fallbackRole =
          (currentUser?.app_metadata?.role as UserProfile["role"]) ||
          (currentUser?.user_metadata?.role as UserProfile["role"]) ||
          "user";

        const resolvedEmail =
          currentUser?.email ||
          (currentUser?.user_metadata?.email as string | undefined) ||
          (currentUser?.identities?.find((id) => id.identity_data?.email)?.identity_data?.email as string | undefined) ||
          null;

        const newProfileData: UserProfile = {
          id: userId,
          email: resolvedEmail,
          display_name: fallbackDisplayName,
          avatar_url: fallbackAvatar,
          role: fallbackRole,
        };

        setProfile(newProfileData);

        // Auto-provision in database only if profile doesn't exist yet (never overwrite role)
        supabase
          .from("profiles")
          .insert({
            id: userId,
            email: resolvedEmail,
            display_name: fallbackDisplayName,
            avatar_url: fallbackAvatar,
            role: fallbackRole,
          })
          .then((res: { error?: { message?: string } | null }) => {
            if (res?.error) {
              console.warn("Auto-provision profile:", res.error.message);
            }
          });
      }
    } catch {
      // Graceful fallback
      if (currentUser) {
        const resolvedEmail =
          currentUser.email ||
          (currentUser.user_metadata?.email as string | undefined) ||
          (currentUser.identities?.find((id) => id.identity_data?.email)?.identity_data?.email as string | undefined) ||
          null;

        setProfile({
          id: userId,
          email: resolvedEmail,
          display_name: currentUser.email?.split("@")[0] || "Producer",
          avatar_url: null,
          role: "user",
        });
      }
    }
  }, [supabase]);

  const refreshProfile = useCallback(async () => {
    if (user?.id) {
      await fetchProfile(user.id, user);
    }
  }, [user, fetchProfile]);

  useEffect(() => {
    let isMounted = true;

    async function initAuth() {
      try {
        const {
          data: { session },
        } = await supabase.auth.getSession();

        if (isMounted) {
          const activeUser = session?.user ?? null;
          setUser(activeUser);
          if (activeUser) {
            await fetchProfile(activeUser.id, activeUser);
          } else {
            setProfile(null);
          }
        }
      } catch (err) {
        console.error("Auth init error:", err);
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    initAuth();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(
      async (_event: AuthChangeEvent, session: Session | null) => {
        const activeUser = session?.user ?? null;
      setUser(activeUser);
      if (activeUser) {
        await fetchProfile(activeUser.id, activeUser);
      } else {
        setProfile(null);
      }
      setIsLoading(false);
    });

    return () => {
      isMounted = false;
      subscription.unsubscribe();
    };
  }, [supabase, fetchProfile]);

  const [isSigningOut, setIsSigningOut] = useState(false);

  const signOut = useCallback(async () => {
    setIsSigningOut(true);
    try {
      await supabase.auth.signOut();
    } catch (err) {
      console.error("Error signing out:", err);
    } finally {
      if (typeof window !== "undefined") {
        setTimeout(() => {
          window.location.href = "/";
        }, 900);
      }
    }
  }, [supabase]);

  const rawRole =
    profile?.role ||
    (user?.app_metadata?.role as string) ||
    (user?.user_metadata?.role as string) ||
    "user";
  const role: UserProfile["role"] =
    typeof rawRole === "string" && rawRole.trim().toLowerCase() === "admin"
      ? "admin"
      : "user";
  const isAdmin = role === "admin";

  const activeDisplayName =
    profile?.display_name ||
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "Producer";

  const lastDisplayNameRef = useRef(activeDisplayName);
  if (activeDisplayName && activeDisplayName !== "Producer") {
    lastDisplayNameRef.current = activeDisplayName;
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        profile,
        role,
        isAdmin,
        isLoading,
        isSigningOut,
        signOut,
        refreshProfile,
      }}
    >
      {children}
      <SignOutModal
        isOpen={isSigningOut}
        displayName={lastDisplayNameRef.current}
      />
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
