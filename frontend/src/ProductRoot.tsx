import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "./App";
import { fetchMaps } from "./api";
import { fetchAuthSession, logout, type AuthSessionState } from "./authApi";
import { EventsPage } from "./components/EventsPage";
import { HomePage } from "./components/HomePage";
import { LoginDialog } from "./components/LoginDialog";
import { ProductShell } from "./components/ProductShell";
import { I18nProvider } from "./i18n";

const authSessionKey = ["auth", "session"] as const;

export function ProductRoot() {
  const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
  if (!isProductRoute(pathname)) return <App />;
  return <I18nProvider><ProductExperience pathname={pathname} /></I18nProvider>;
}

function ProductExperience({ pathname }: { pathname: string }) {
  const queryClient = useQueryClient();
  const [loginOpen, setLoginOpen] = React.useState(false);
  const auth = useQuery({
    queryKey: authSessionKey,
    queryFn: fetchAuthSession,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: 1
  });
  const matches = useQuery({
    queryKey: ["product", "matches"],
    queryFn: fetchMaps,
    refetchInterval: 15_000,
    retry: 1
  });
  const session = auth.data;
  const signedIn = Boolean(session?.enabled && session.authenticated && session.user);
  const hasPro = Boolean(
    session?.entitlements.includes("ai_decisions") &&
      session?.entitlements.includes("realtime_notifications")
  );
  const isHome = pathname === "/";

  const handleAuthenticated = (next: AuthSessionState) => {
    queryClient.setQueryData(authSessionKey, next);
    setLoginOpen(false);
  };

  const handleLogout = async () => {
    await logout();
    queryClient.setQueryData<AuthSessionState>(authSessionKey, {
      enabled: session?.enabled ?? true,
      authenticated: false,
      user: null,
      entitlements: [],
      grants: [],
      providers: session?.providers
    });
  };

  return (
    <ProductShell
      active={isHome ? "home" : "events"}
      session={session}
      onLogin={() => setLoginOpen(true)}
      onLogout={handleLogout}
    >
      {isHome ? (
        <HomePage
          matches={matches.data ?? []}
          loading={matches.isLoading}
          signedIn={signedIn}
          hasPro={hasPro}
          onLogin={() => setLoginOpen(true)}
        />
      ) : (
        <EventsPage
          matches={matches.data ?? []}
          loading={matches.isLoading}
          pathname={pathname}
          hasPro={hasPro}
        />
      )}
      {loginOpen && session?.enabled !== false && (
        <LoginDialog
          session={session}
          onClose={() => setLoginOpen(false)}
          onAuthenticated={handleAuthenticated}
        />
      )}
    </ProductShell>
  );
}

function isProductRoute(pathname: string): boolean {
  return pathname === "/" || pathname === "/events" || pathname.startsWith("/events/");
}
