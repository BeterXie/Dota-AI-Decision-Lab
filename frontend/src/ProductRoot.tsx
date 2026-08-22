import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMaps } from "./api";
import { fetchAuthSession, logout, type AuthSessionState } from "./authApi";
import { AccountPage } from "./components/AccountPage";
import { AdminRuntimePage } from "./components/AdminRuntimePage";
import { EventsPage } from "./components/EventsPage";
import { HomePage } from "./components/HomePage";
import { LoginDialog } from "./components/LoginDialog";
import { LegalPage, type LegalPageKind } from "./components/LegalPage";
import { MatchPage } from "./components/MatchPage";
import { PremiumSurface, type PremiumSurfaceKey } from "./components/PremiumSurface";
import { ProductShell, type ProductNavKey } from "./components/ProductShell";
import { TeamPage } from "./components/TeamPage";
import { I18nProvider, useI18n } from "./i18n";
import { matchIdFromPath } from "./matches";
import { teamSlugFromPath } from "./teams";

const authSessionKey = ["auth", "session"] as const;

export function ProductRoot() {
  const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
  return <I18nProvider><ProductExperience pathname={pathname} /></I18nProvider>;
}

function ProductExperience({ pathname }: { pathname: string }) {
  const queryClient = useQueryClient();
  const [loginOpen, setLoginOpen] = React.useState(false);
  const premiumSurface = premiumSurfaceForPath(pathname);
  const adminRoute = pathname === "/admin/runtime" || pathname.startsWith("/admin/runtime/");
  const accountRoute = pathname === "/account" || pathname.startsWith("/account/");
  const legalPage = legalPageForPath(pathname);
  const eventsRoute = pathname === "/events" || pathname.startsWith("/events/");
  const isHome = pathname === "/";
  const matchRouteId = matchIdFromPath(pathname);
  const teamRouteSlug = teamSlugFromPath(pathname);
  const needsMatchDirectory = isHome || eventsRoute || matchRouteId !== null || teamRouteSlug !== null;
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
    enabled: needsMatchDirectory,
    refetchInterval: 15_000,
    retry: 1
  });
  const session = auth.data;
  const signedIn = Boolean(session?.enabled && session.authenticated && session.user);

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
      runtime_admin: false,
      providers: session?.providers
    });
  };

  if (adminRoute) {
    return (
      <>
        <AdminRuntimePage
          pathname={pathname}
          session={session}
          authLoading={auth.isLoading}
          onLogin={() => setLoginOpen(true)}
          onLogout={handleLogout}
        />
        {loginOpen && session?.enabled !== false && (
          <LoginDialog
            session={session}
            onClose={() => setLoginOpen(false)}
            onAuthenticated={handleAuthenticated}
          />
        )}
      </>
    );
  }

  let page: React.ReactNode;
  if (accountRoute) {
    page = (
      <AccountPage
        session={session}
        authLoading={auth.isLoading}
        onLogin={() => setLoginOpen(true)}
        onLogout={handleLogout}
      />
    );
  } else if (legalPage) {
    page = <LegalPage kind={legalPage} />;
  } else if (premiumSurface) {
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
        onLogin={() => setLoginOpen(true)}
      />
    );
  } else if (teamRouteSlug) {
    page = (
      <TeamPage
        slug={teamRouteSlug}
        matches={matches.data ?? []}
        matchesLoading={matches.isLoading}
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
  } else if (eventsRoute) {
    page = (
      <EventsPage
        matches={matches.data ?? []}
        loading={matches.isLoading}
        error={Boolean(matches.error)}
        onRetry={() => void matches.refetch()}
        pathname={pathname}
      />
    );
  } else {
    page = <ProductNotFound />;
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

function legalPageForPath(pathname: string): LegalPageKind | null {
  if (pathname === "/terms" || pathname.startsWith("/terms/")) return "terms";
  if (pathname === "/privacy" || pathname.startsWith("/privacy/")) return "privacy";
  return null;
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
  if (pathname === "/account" || pathname.startsWith("/account/")) return null;
  if (premiumSurface === "performance") return "performance";
  if (premiumSurface === "review") return "review";
  if (premiumSurface === "billing") return "billing";
  if (premiumSurface === "notifications") return null;
  if (pathname === "/") return "home";
  if (
    pathname === "/events" ||
    pathname.startsWith("/events/") ||
    pathname.startsWith("/matches/") ||
    pathname.startsWith("/teams/")
  ) return "events";
  return null;
}

const ProductNotFound: React.FC = () => {
  const { locale } = useI18n();
  return (
    <section className="product-container match-not-found">
      <span aria-hidden="true">404</span>
      <h1>{locale === "zh-CN" ? "没有找到这个页面" : "Page not found"}</h1>
      <p>{locale === "zh-CN" ? "这个地址不存在，或者页面已经移动。" : "This address does not exist, or the page has moved."}</p>
      <a className="product-btn product-btn-primary" href="/">{locale === "zh-CN" ? "返回首页" : "Back home"}</a>
    </section>
  );
};
