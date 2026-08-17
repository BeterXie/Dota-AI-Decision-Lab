import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "./App";
import { fetchMaps } from "./api";
import { fetchAuthSession, logout, type AuthSessionState } from "./authApi";
import { EventsPage } from "./components/EventsPage";
import { HomePage } from "./components/HomePage";
import { LoginDialog } from "./components/LoginDialog";
import { MatchPage } from "./components/MatchPage";
import { PremiumSurface, type PremiumSurfaceKey } from "./components/PremiumSurface";
import { ProductShell, type ProductNavKey } from "./components/ProductShell";
import { I18nProvider } from "./i18n";
import { matchIdFromPath } from "./matches";

const authSessionKey = ["auth", "session"] as const;

export function ProductRoot() {
  const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
  if (!isProductRoute(pathname)) return <App />;
  return <I18nProvider><ProductExperience pathname={pathname} /></I18nProvider>;
}

function ProductExperience({ pathname }: { pathname: string }) {
  const queryClient = useQueryClient();
  const [loginOpen, setLoginOpen] = React.useState(false);
  const premiumSurface = premiumSurfaceForPath(pathname);
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
    enabled: premiumSurface === null,
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
  const matchRouteId = matchIdFromPath(pathname);

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

  let page: React.ReactNode;
  if (premiumSurface) {
    page = (
      <PremiumSurface
        surface={premiumSurface}
        session={session}
        authLoading={auth.isLoading}
        onLogin={() => setLoginOpen(true)}
      />
    );
  } else if (isHome) {
    page = (
      <HomePage
        matches={matches.data ?? []}
        loading={matches.isLoading}
        signedIn={signedIn}
        hasPro={hasPro}
        onLogin={() => setLoginOpen(true)}
      />
    );
  } else if (matchRouteId) {
    page = (
      <MatchPage
        matches={matches.data ?? []}
        matchesLoading={matches.isLoading}
        routeId={matchRouteId}
        session={session}
        onLogin={() => setLoginOpen(true)}
      />
    );
  } else {
    page = (
      <EventsPage
        matches={matches.data ?? []}
        loading={matches.isLoading}
        pathname={pathname}
        hasPro={hasPro}
      />
    );
  }

  return (
    <ProductShell
      active={activeNavForPath(pathname, premiumSurface)}
      session={session}
      onLogin={() => setLoginOpen(true)}
      onLogout={handleLogout}
    >
      {page}
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

function premiumSurfaceForPath(pathname: string): PremiumSurfaceKey | null {
  if (pathname === "/performance" || pathname.startsWith("/performance/")) return "performance";
  if (pathname === "/review" || pathname.startsWith("/review/")) return "review";
  if (pathname === "/billing" || pathname.startsWith("/billing/")) return "billing";
  if (pathname === "/notifications" || pathname.startsWith("/notifications/")) return "notifications";
  return null;
}

function activeNavForPath(
  pathname: string,
  premiumSurface: PremiumSurfaceKey | null
): ProductNavKey | null {
  if (premiumSurface === "performance") return "performance";
  if (premiumSurface === "review") return "review";
  if (premiumSurface === "billing") return "billing";
  if (premiumSurface === "notifications") return null;
  if (pathname === "/") return "home";
  return "events";
}

function isProductRoute(pathname: string): boolean {
  return (
    pathname === "/" ||
    pathname === "/events" ||
    pathname.startsWith("/events/") ||
    pathname.startsWith("/matches/") ||
    premiumSurfaceForPath(pathname) !== null
  );
}
