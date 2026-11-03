import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function updateSession(request: NextRequest) {
  let supabaseResponse = NextResponse.next({
    request,
  });

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Si las variables no están definidas, dejamos pasar la petición sin
  // autenticación — las páginas públicas (/, /login, /register) deben cargarse
  // aun cuando Supabase no esté configurado en este entorno.
  if (!supabaseUrl || !supabaseAnonKey) {
    return supabaseResponse;
  }

  let user = null;
  try {
    const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          supabaseResponse = NextResponse.next({
            request,
          });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    });

    const {
      data: { user: authenticatedUser },
    } = await supabase.auth.getUser();

    user = authenticatedUser;
  } catch (error) {
    // Si falla cualquier cosa (client initialization, cookie parsing,
    // getUser(), etc.), seguimos sin usuario — el frontend maneja la
    // sesión por su cuenta y las rutas públicas siempre quedan accesibles.
    console.error("Supabase middleware error:", error);
  }

  // Rutas públicas: landing ("/"), auth, APIs y voz.
  const pathname = request.nextUrl.pathname;
  const isAuthRoute =
    pathname.startsWith("/login") ||
    pathname.startsWith("/register") ||
    pathname.startsWith("/auth/callback");

  const isPublicRoute =
    pathname === "/" ||
    isAuthRoute ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/voz");

  // 1. Si el usuario está logueado y visita login/registro → redirigir a "/"
  if (user && (pathname === "/login" || pathname === "/register")) {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
  }

  // 2. Si el usuario NO está logueado y intenta acceder a rutas que NO son públicas → redirigir a "/login"
  if (!user && !isPublicRoute) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    // Se incluye el query string para que el login aterrice en la pantalla correcta.
    if (pathname !== "/") {
      url.searchParams.set("redirect", `${pathname}${request.nextUrl.search}`);
    }
    return NextResponse.redirect(url);
  }

  // 3. Usuario logueado o ruta pública → responder normalmente.
  return supabaseResponse;
}
