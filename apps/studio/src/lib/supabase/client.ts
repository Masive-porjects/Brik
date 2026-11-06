import { createBrowserClient } from "@supabase/ssr";

let client: ReturnType<typeof createBrowserClient> | undefined;

export function createClient() {
  if (client) return client;

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error(
      "Missing Supabase environment variables. Make sure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are set.",
    );
  }

  client = createBrowserClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      get: (key) => {
        if (typeof document === "undefined") return undefined;
        const match = document.cookie.match(
          new RegExp(
            "(?:^|; )" +
              key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
              "=([^;]*)",
          ),
        );
        return match ? match[1] : undefined;
      },
      set: (key, value, options) => {
        if (typeof document === "undefined") return;
        let cookieString = `${key}=${value}; path=/`;
        if (options.maxAge) cookieString += `; max-age=${options.maxAge}`;
        if (options.expires)
          cookieString += `; expires=${options.expires.toUTCString()}`;
        if (options.domain) cookieString += `; domain=${options.domain}`;
        if (options.secure) cookieString += "; secure";
        if (options.sameSite) cookieString += `; samesite=${options.sameSite}`;
        document.cookie = cookieString;
      },
      remove: (key, options) => {
        if (typeof document === "undefined") return;
        let cookieString = `${key}=; path=/; max-age=0`;
        if (options.domain) cookieString += `; domain=${options.domain}`;
        if (options.secure) cookieString += "; secure";
        if (options.sameSite) cookieString += `; samesite=${options.sameSite}`;
        document.cookie = cookieString;
      },
    },
    auth: {
      persistSession: true,
      autoRefreshToken: true,
    },
  });
  return client;
}
