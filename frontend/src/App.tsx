import React, { lazy, Suspense, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchJobs,
  fetchMap,
  fetchMaps,
  fetchRuntime,
  queryKeys,
  useRuntimeSocket,
  type AiDecision,
  type FutureOddsCapture,
  type MapDetail,
  type MapSummary
} from "./api";
import { fetchAuthSession, logout, type AuthSessionState } from "./authApi";
import { I18nProvider, useI18n } from "./i18n";
import { AppShell } from "./components/AppShell";
import { AuthAccountBadge } from "./components/AuthAccountBadge";
import { LoginPage } from "./components/LoginPage";

const ReviewPage = lazy(() =>
  import("./components/ReviewPage").then((module) => ({ default: module.ReviewPage }))
);
const AiPerformancePage = lazy(() =>
  import("./components/AiPerformancePage").then((module) => ({ default: module.AiPerformancePage }))
);
const NotificationCenterPage = lazy(() =>
  import("./components/NotificationCenterPage").then((module) => ({
    default: module.NotificationCenterPage
  }))
);
const BillingPage = lazy(() =>
  import("./components/BillingPage").then((module) => ({ default: module.BillingPage }))
);
const authSessionKey = ["auth", "session"] as const;
const AI_DECISIONS_ENTITLEMENT = "ai_decisions";
const REALTIME_NOTIFICATIONS_ENTITLEMENT = "realtime_notifications";

interface PremiumAiPayload {
  canonical_map_id: string;
  canonical_series_id?: string | null;
  latest_snapshot: MapSummary["latest_snapshot"];
  decisions: AiDecision[];
  checkpoint_decisions: AiDecision[];
  snapshot_payload?: MapDetail["snapshot_payload"];
  future_odds: FutureOddsCapture[];
}

export function App() {
  return (
    <I18nProvider>
      <AuthenticatedApp />
    </I18nProvider>
  );
}

function AuthenticatedApp() {
  const queryClient = useQueryClient();
  const { locale } = useI18n();
  const [loginOpen, setLoginOpen] = useState(false);
  const auth = useQuery({
    queryKey: authSessionKey,
    queryFn: fetchAuthSession,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: 1
  });
  const session = auth.data;
  const hasAiAccess = Boolean(session?.entitlements?.includes(AI_DECISIONS_ENTITLEMENT));
  const hasNotificationAccess = Boolean(
    session?.entitlements?.includes(REALTIME_NOTIFICATIONS_ENTITLEMENT) ||
      session?.grants?.some((grant) => grant.entitlement === REALTIME_NOTIFICATIONS_ENTITLEMENT)
  );
  const hasGlobalNotificationAccess = Boolean(
    session?.entitlements?.includes(REALTIME_NOTIFICATIONS_ENTITLEMENT)
  );
  const hasPro = hasAiAccess && hasGlobalNotificationAccess;
  const isSignedIn = Boolean(session?.enabled && session.authenticated && session.user);

  const handleAuthenticated = (next: AuthSessionState) => {
    queryClient.setQueryData(authSessionKey, next);
    setLoginOpen(false);
  };

  if (loginOpen) {
    return (
      <>
        <LoginPage onAuthenticated={handleAuthenticated} />
        <div className="auth-account-badge">
          <button type="button" onClick={() => setLoginOpen(false)}>
            {locale === "zh-CN" ? "继续浏览比赛" : "Continue browsing"}
          </button>
        </div>
      </>
    );
  }

  const handleLogout = async () => {
    await logout();
    queryClient.clear();
    queryClient.setQueryData<AuthSessionState>(authSessionKey, {
      enabled: true,
      authenticated: false,
      user: null,
      entitlements: [],
      grants: []
    });
  };

  const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
  const performanceRoute = isAiPerformanceRoute(pathname);
  const reviewRoute = isReviewRoute(pathname);
  const notificationRoute = isNotificationRoute(pathname);
  const billingRoute = isBillingRoute(pathname);
  let content: React.ReactNode;
  if (billingRoute) {
    content = (
      <Suspense fallback={<div className="auth-bootstrap">Pro Billing</div>}>
        <BillingPage
          authenticated={isSignedIn}
          hasPro={hasPro}
          onLogin={() => setLoginOpen(true)}
        />
      </Suspense>
    );
  } else if (notificationRoute) {
    if (auth.isLoading) {
      content = <div className="auth-bootstrap">Dota AI Decision Lab</div>;
    } else if (hasNotificationAccess && session?.user) {
      content = (
        <Suspense fallback={<div className="auth-bootstrap">Notification Center</div>}>
          <NotificationCenterPage userEmail={session.user.email} />
        </Suspense>
      );
    } else {
      content = (
        <NotificationAccessGate
          authenticated={isSignedIn}
          authEnabled={session?.enabled !== false}
          onLogin={() => setLoginOpen(true)}
        />
      );
    }
  } else if (performanceRoute) {
    content = hasAiAccess ? (
      <Suspense fallback={<div className="auth-bootstrap">AI Performance</div>}>
        <AiPerformancePage />
      </Suspense>
    ) : (
      <PremiumAnalyticsGate
        surface="performance"
        authenticated={isSignedIn}
        authEnabled={session?.enabled !== false}
        onLogin={() => setLoginOpen(true)}
      />
    );
  } else if (reviewRoute) {
    content = hasAiAccess ? (
      <Suspense fallback={<div className="auth-bootstrap">Dota AI Decision Lab</div>}>
        <ReviewPage />
      </Suspense>
    ) : (
      <PremiumAnalyticsGate
        surface="review"
        authenticated={isSignedIn}
        authEnabled={session?.enabled !== false}
        onLogin={() => setLoginOpen(true)}
      />
    );
  } else {
    content = (
      <DashboardApp
        session={session}
        authLoading={auth.isLoading}
        onLogin={() => setLoginOpen(true)}
      />
    );
  }

  return (
    <>
      {content}
      {session?.enabled && session.user ? (
        <AuthAccountBadge user={session.user} onLogout={handleLogout} />
      ) : session?.enabled && !session.authenticated ? (
        <div className="auth-account-badge">
          <span className="auth-account-dot" aria-hidden="true" />
          <button type="button" onClick={() => setLoginOpen(true)}>
            {locale === "zh-CN" ? "登录" : "Sign in"}
          </button>
        </div>
      ) : null}
    </>
  );
}

export function isAiPerformanceRoute(pathname: string): boolean {
  return pathname === "/performance" || pathname.startsWith("/performance/");
}

export function isReviewRoute(pathname: string): boolean {
  return pathname === "/review" || pathname.startsWith("/review/");
}

export function isNotificationRoute(pathname: string): boolean {
  return pathname === "/notifications" || pathname.startsWith("/notifications/");
}

export function isBillingRoute(pathname: string): boolean {
  return pathname === "/billing" || pathname.startsWith("/billing/");
}

function DashboardApp({
  session,
  authLoading,
  onLogin
}: {
  session: AuthSessionState | undefined;
  authLoading: boolean;
  onLogin: () => void;
}) {
  useRuntimeSocket();
  const queryClient = useQueryClient();
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null);
  const isSignedIn = Boolean(session?.enabled && session.authenticated && session.user);
  const canFetchOperationalData = Boolean(session && (!session.enabled || isSignedIn));

  const runtime = useQuery({
    queryKey: queryKeys.runtime,
    queryFn: fetchRuntime,
    refetchInterval: 5000
  });
  const maps = useQuery({
    queryKey: queryKeys.maps,
    queryFn: fetchMaps,
    refetchInterval: 5000
  });
  const jobs = useQuery({
    queryKey: queryKeys.jobs,
    queryFn: fetchJobs,
    enabled: canFetchOperationalData,
    refetchInterval: 5000
  });

  const liveCanonicalMapIds = (maps.data ?? [])
    .filter((match) => match.phase === "LIVE" && match.canonical_map_id)
    .map((match) => match.canonical_map_id as string);
  const liveDetailQueries = useQueries({
    queries: liveCanonicalMapIds.map((canonicalMapId) => ({
      queryKey: queryKeys.map(canonicalMapId),
      queryFn: () => fetchMap(canonicalMapId),
      refetchInterval: 4000
    }))
  });
  const liveDetailsById = new Map<string, MapDetail>();
  for (const query of liveDetailQueries) {
    if (query.data?.canonical_map_id) {
      liveDetailsById.set(query.data.canonical_map_id, query.data);
    }
  }
  const enrichedMatches: MapSummary[] = (maps.data ?? []).map((match) =>
    match.canonical_map_id ? liveDetailsById.get(match.canonical_map_id) ?? match : match
  );

  const activeMapId = chooseActiveMapId(selectedMapId, enrichedMatches);
  const selectedMatch = enrichedMatches.find((match) => match.id === activeMapId) || enrichedMatches[0];
  const selectedCanonicalMapId = selectedMatch?.canonical_map_id ?? null;
  const selectedSeriesId = selectedMatch?.series_id ?? null;
  const aiScope = accessScopeForResource(
    session,
    AI_DECISIONS_ENTITLEMENT,
    selectedSeriesId,
    selectedCanonicalMapId
  );
  const hasSelectedAiAccess = aiScope !== null;

  const detail = useQuery({
    queryKey: selectedCanonicalMapId ? queryKeys.map(selectedCanonicalMapId) : ["map", "none"],
    queryFn: () => fetchMap(selectedCanonicalMapId!),
    enabled: Boolean(selectedCanonicalMapId),
    placeholderData: isEmbeddedDetail(selectedMatch) ? selectedMatch : undefined,
    refetchInterval: 4000
  });
  const premium = useQuery({
    queryKey: selectedCanonicalMapId ? ["map-ai", selectedCanonicalMapId] : ["map-ai", "none"],
    queryFn: () => fetchPremiumAi(selectedCanonicalMapId!),
    enabled: Boolean(selectedCanonicalMapId && hasSelectedAiAccess),
    refetchInterval: 4000
  });

  const activeDetail = detail.data
    ? ({
        ...detail.data,
        ...(premium.data ?? {}),
        latest_snapshot: premium.data?.latest_snapshot ?? detail.data.latest_snapshot
      } as MapDetail)
    : undefined;
  const shellMatches: MapSummary[] = activeDetail?.canonical_map_id
    ? enrichedMatches.map((match) =>
        match.canonical_map_id === activeDetail.canonical_map_id ? activeDetail : match
      )
    : enrichedMatches;

  const handleRefresh = () => {
    void queryClient.invalidateQueries();
  };

  return (
    <AppShell
      runtime={runtime.data}
      jobs={jobs.data}
      matches={shellMatches}
      selectedMatch={selectedMatch}
      detail={activeDetail}
      detailLoading={detail.isLoading}
      detailError={detail.error}
      selectedMapId={activeMapId}
      onSelectMatch={setSelectedMapId}
      onRefresh={handleRefresh}
      aiAccess={{
        authEnabled: session?.enabled !== false,
        authenticated: isSignedIn,
        entitled: hasSelectedAiAccess,
        scope: aiScope,
        loading: authLoading || premium.isLoading,
        upgradeHref: selectedSeriesId ? `/billing?series=${encodeURIComponent(selectedSeriesId)}` : "/billing"
      }}
      onLogin={onLogin}
    />
  );
}

function accessScopeForResource(
  session: AuthSessionState | undefined,
  entitlement: string,
  seriesId: string | null,
  mapId: string | null
): "GLOBAL" | "SERIES" | "MAP" | null {
  if (session?.entitlements?.includes(entitlement)) return "GLOBAL";
  const grants = session?.grants ?? [];
  if (
    seriesId &&
    grants.some(
      (grant) =>
        grant.entitlement === entitlement &&
        grant.scope_type === "SERIES" &&
        grant.scope_ref === seriesId
    )
  ) {
    return "SERIES";
  }
  if (
    mapId &&
    grants.some(
      (grant) =>
        grant.entitlement === entitlement && grant.scope_type === "MAP" && grant.scope_ref === mapId
    )
  ) {
    return "MAP";
  }
  return null;
}

function chooseActiveMapId(selectedMapId: string | null, matches: MapSummary[]): string | null {
  if (selectedMapId && matches.some((match) => match.id === selectedMapId)) {
    return selectedMapId;
  }
  if (matches.length === 0) return null;

  const liveMatches = matches.filter((match) => match.phase === "LIVE");
  if (liveMatches.length > 0) return liveMatches[0].id;

  const upcomingMatches = matches.filter(
    (match) => match.phase === "PREMATCH" || match.phase === "UNKNOWN"
  );
  if (upcomingMatches.length > 0) {
    const sortedUpcoming = [...upcomingMatches].sort((a, b) => {
      const timeA = a.scheduled_at ? Date.parse(a.scheduled_at) : Infinity;
      const timeB = b.scheduled_at ? Date.parse(b.scheduled_at) : Infinity;
      return timeA - timeB;
    });
    return sortedUpcoming[0].id;
  }

  const finishedMatches = matches.filter(
    (match) => match.phase === "POSTMATCH" || match.phase === "AWAITING_RESULT"
  );
  if (finishedMatches.length > 0) {
    const sortedFinished = [...finishedMatches].sort((a, b) => {
      const timeA = a.scheduled_at ? Date.parse(a.scheduled_at) : 0;
      const timeB = b.scheduled_at ? Date.parse(b.scheduled_at) : 0;
      return timeB - timeA;
    });
    return sortedFinished[0].id;
  }

  return matches[0].id;
}

function isEmbeddedDetail(match: MapSummary | undefined): match is MapDetail {
  return Boolean(match && "market_timeline" in match && "result_evidence" in match);
}

async function fetchPremiumAi(id: string): Promise<PremiumAiPayload> {
  const response = await fetch(`/api/maps/${id}/ai-decisions`, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<PremiumAiPayload>;
}

function PremiumAnalyticsGate({
  surface,
  authenticated,
  authEnabled,
  onLogin
}: {
  surface: "review" | "performance";
  authenticated: boolean;
  authEnabled: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  const performance = surface === "performance";
  const title = locale === "zh-CN"
    ? performance ? "AI Performance 属于 Pro 权限" : "AI 复盘属于 Pro 权限"
    : performance ? "AI Performance is a Pro feature" : "AI Review is a Pro feature";
  const description = locale === "zh-CN"
    ? performance
      ? "普通比赛数据保持公开；跨比赛模型成绩、实验版本对比和完整决策追溯属于全局 Pro。单个系列赛通行证不会开放全局模型历史。"
      : "普通比赛数据保持公开；跨比赛 AI 历史复盘属于全局 Pro。单个系列赛通行证只解锁所购买比赛的 AI 与实时通知。"
    : performance
      ? "Match data stays public. Cross-match model performance, experiment comparison and decision audit history require global Pro; a series pass does not unlock global model history."
      : "Match data stays public. Cross-match AI review requires global Pro; a series pass unlocks only the purchased series AI and alerts.";
  const denied = locale === "zh-CN"
    ? performance ? "当前账号尚未拥有全局 AI Performance 权限。" : "当前账号尚未拥有全局 AI Review 权限。"
    : performance ? "This account does not have global AI Performance access yet." : "This account does not have global AI Review access yet.";

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-card-header">
          <div className="auth-brand-mark">◆</div>
          <div>
            <div className="auth-eyebrow">PRO INTELLIGENCE</div>
            <h1>{title}</h1>
          </div>
        </div>
        <p className="auth-description">{description}</p>
        {!authenticated && authEnabled && (
          <button className="auth-primary-btn" type="button" onClick={onLogin}>
            {locale === "zh-CN" ? "登录以查看权限" : "Sign in to check access"}
          </button>
        )}
        {authenticated && <div className="auth-error" role="status">{denied}</div>}
        {!authEnabled && (
          <div className="auth-error" role="status">
            {locale === "zh-CN"
              ? "当前运行环境尚未启用登录，因此 Pro AI 接口保持关闭。"
              : "Authentication is disabled in this runtime, so premium AI access remains closed."}
          </div>
        )}
      </section>
    </main>
  );
}

function NotificationAccessGate({
  authenticated,
  authEnabled,
  onLogin
}: {
  authenticated: boolean;
  authEnabled: boolean;
  onLogin: () => void;
}) {
  const { locale } = useI18n();
  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-card-header">
          <div className="auth-brand-mark">◆</div>
          <div>
            <div className="auth-eyebrow">REALTIME PRO</div>
            <h1>
              {locale === "zh-CN"
                ? "实时 Notification Center 属于付费权限"
                : "Realtime Notification Center requires paid access"}
            </h1>
          </div>
        </div>
        <p className="auth-description">
          {locale === "zh-CN"
            ? "全局 Pro 或有效的系列赛通行证都可以绑定邮箱、QQ 和微信；实际通知只会发送你拥有权限的比赛。"
            : "Global Pro or an active series pass can bind Email, QQ and WeChat. Alerts are sent only for matches covered by your access grants."}
        </p>
        {!authenticated && authEnabled && (
          <button className="auth-primary-btn" type="button" onClick={onLogin}>
            {locale === "zh-CN" ? "登录以查看权限" : "Sign in to check access"}
          </button>
        )}
        {authenticated && (
          <div className="auth-error" role="status">
            {locale === "zh-CN"
              ? "当前账号没有任何有效的实时通知权限。"
              : "This account does not have any active realtime notification grant."}
          </div>
        )}
        {!authEnabled && (
          <div className="auth-error" role="status">
            {locale === "zh-CN"
              ? "当前运行环境尚未启用登录，因此用户级实时通知保持关闭。"
              : "Authentication is disabled, so user-scoped realtime notifications remain closed."}
          </div>
        )}
        <a className="auth-secondary-link" href="/">
          {locale === "zh-CN" ? "返回比赛" : "Back to matches"}
        </a>
      </section>
    </main>
  );
}
