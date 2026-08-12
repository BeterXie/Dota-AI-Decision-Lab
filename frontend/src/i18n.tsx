import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Locale = "en" | "zh-CN";

const STORAGE_KEY = "dota-ai-decision-lab-locale";

const messages = {
  en: {
    language: "Language",
    refreshData: "Refresh data",
    trackedMaps: "Tracked maps",
    noCanonicalMaps: "No canonical maps",
    waitingForProviderDiscovery: "Waiting for provider discovery.",
    mapFeedUnavailable: "Map feed unavailable",
    mapDetailUnavailable: "Map detail unavailable",
    loadingReadiness: "Loading readiness",
    businessReadiness: "Business readiness",
    mapIntelligenceViews: "Map intelligence views",
    unknownTeam: "Unknown",
    teamA: "Team A",
    teamB: "Team B",
    map: "Map",
    valve: "Valve",
    unresolved: "unresolved",
    versus: "vs",
    marketUnavailable: "Market unavailable",
    dataQuality: "Data quality",
    decisionBlocked: "Decision blocked",
    decisionDegraded: "Decision degraded",
    market: "Market",
    selection: "Selection",
    odds: "Odds",
    fair: "Fair",
    marketOddsTimeline: "Market odds timeline",
    noRayBetOdds: "No RayBet odds observations for this map.",
    draftIntelligence: "Draft Intelligence",
    currentEdge: "Current edge",
    next5m: "Next 5m",
    peakMinute: "Peak minute",
    peakEdge: "Peak edge",
    pure: "Pure",
    playerAdjusted: "Player adjusted",
    draftMinuteCurve: "Draft minute curve",
    noRoshCurve: "No validated R.O.S.H. curve is available.",
    independentAiDecisions: "Independent AI decisions",
    confidence: "Confidence",
    reasons: "Reasons",
    counterArguments: "Counter arguments",
    qualityConcerns: "Quality concerns",
    noAiDecisions: "No AI decisions exist for the latest snapshot.",
    live: "Live",
    historical: "Historical",
    runtime: "Runtime",
    gameTime: "Game time",
    kills: "Kills",
    radiantNetWorth: "Radiant NW",
    sync: "Sync",
    p90Lag: "P90 lag",
    samples: "Samples",
    radiantNetWorthLead: "Radiant net worth lead",
    dltvLiveTimeline: "DLTV live state timeline",
    noDltvStates: "No normalized DLTV fast states are available.",
    noHistoricalSnapshot: "No Historical snapshot is attached.",
    baseElo: "Base Elo",
    recentForm: "Recent form",
    rosterStrength: "Roster strength",
    rosterStability: "Roster stability",
    position: "Pos",
    base: "Base",
    recent: "Recent",
    hero: "Hero",
    workers: "Workers",
    worker: "Worker",
    state: "State",
    messages: "Messages",
    restarts: "Restarts",
    lastSuccess: "Last success",
    durableJobs: "Durable jobs",
    attempts: "attempts",
    unknownError: "Unknown error",
    noTerminalFailures: "No terminal job failures.",
    waitingCanonicalMap: "Waiting for canonical map discovery",
    runtimeStatusVisible: "Runtime health and provider state remain visible above.",
    noSnapshot: "NO SNAPSHOT",
    unknown: "unknown",
    notObserved: "not observed",
    invalidTime: "invalid time",
    unknownLatency: "unknown latency"
  },
  "zh-CN": {
    language: "语言",
    refreshData: "刷新数据",
    trackedMaps: "跟踪中的地图",
    noCanonicalMaps: "暂无规范化地图",
    waitingForProviderDiscovery: "正在等待 Provider 发现比赛。",
    mapFeedUnavailable: "地图数据源不可用",
    mapDetailUnavailable: "地图详情不可用",
    loadingReadiness: "正在加载就绪状态",
    businessReadiness: "业务就绪状态",
    mapIntelligenceViews: "地图情报视图",
    unknownTeam: "未知队伍",
    teamA: "队伍 A",
    teamB: "队伍 B",
    map: "地图",
    valve: "Valve",
    unresolved: "未解析",
    versus: "对阵",
    marketUnavailable: "市场数据不可用",
    dataQuality: "数据质量",
    decisionBlocked: "决策已阻止",
    decisionDegraded: "决策已降级",
    market: "市场",
    selection: "选项",
    odds: "赔率",
    fair: "公平概率",
    marketOddsTimeline: "市场赔率时间轴",
    noRayBetOdds: "此地图暂无 RayBet 赔率观测。",
    draftIntelligence: "选人情报",
    currentEdge: "当前优势",
    next5m: "未来 5 分钟",
    peakMinute: "峰值分钟",
    peakEdge: "峰值优势",
    pure: "纯选人",
    playerAdjusted: "选手修正",
    draftMinuteCurve: "选人分钟曲线",
    noRoshCurve: "暂无通过验证的 R.O.S.H. 曲线。",
    independentAiDecisions: "独立 AI 决策",
    confidence: "置信度",
    reasons: "主要理由",
    counterArguments: "反方论据",
    qualityConcerns: "质量问题",
    noAiDecisions: "最新快照暂无 AI 决策。",
    live: "实时",
    historical: "历史",
    runtime: "运行状态",
    gameTime: "比赛时间",
    kills: "击杀",
    radiantNetWorth: "天辉经济差",
    sync: "同步状态",
    p90Lag: "P90 延迟",
    samples: "样本数",
    radiantNetWorthLead: "天辉经济领先",
    dltvLiveTimeline: "DLTV 实时状态时间轴",
    noDltvStates: "暂无规范化 DLTV 快速状态。",
    noHistoricalSnapshot: "当前快照未附带历史情报。",
    baseElo: "基础 Elo",
    recentForm: "近期状态",
    rosterStrength: "阵容强度",
    rosterStability: "阵容稳定性",
    position: "位置",
    base: "基础",
    recent: "近期",
    hero: "英雄",
    workers: "Worker 状态",
    worker: "Worker",
    state: "状态",
    messages: "消息数",
    restarts: "重启次数",
    lastSuccess: "最近成功",
    durableJobs: "持久任务",
    attempts: "次尝试",
    unknownError: "未知错误",
    noTerminalFailures: "没有终止失败的任务。",
    waitingCanonicalMap: "等待规范化地图发现",
    runtimeStatusVisible: "运行健康与 Provider 状态仍显示在上方。",
    noSnapshot: "无快照",
    unknown: "未知",
    notObserved: "尚未观测",
    invalidTime: "时间无效",
    unknownLatency: "延迟未知"
  }
} as const;

export type MessageKey = keyof (typeof messages)["en"];

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "en" || stored === "zh-CN") return stored;
    return window.navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
  });

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<I18nValue>(
    () => ({ locale, setLocale, t: (key) => messages[locale][key] }),
    [locale]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (value === null) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}

export function translate(key: MessageKey, locale: Locale): string {
  return messages[locale][key];
}

const statusMessages: Record<string, Record<Locale, string>> = {
  ACTION_REQUIRED: { en: "ACTION REQUIRED", "zh-CN": "需要处理" },
  BUY_A: { en: "BUY A", "zh-CN": "买入 A" },
  BUY_B: { en: "BUY B", "zh-CN": "买入 B" },
  CAUTION: { en: "CAUTION", "zh-CN": "注意" },
  COMPLETED: { en: "COMPLETED", "zh-CN": "已完成" },
  DATA_CONFLICT: { en: "DATA CONFLICT", "zh-CN": "数据冲突" },
  DEGRADED: { en: "DEGRADED", "zh-CN": "已降级" },
  DRAFT_PARTIAL: { en: "DRAFT PARTIAL", "zh-CN": "选人信息不完整" },
  FAILED: { en: "FAILED", "zh-CN": "失败" },
  FAILED_TERMINAL: { en: "FAILED TERMINAL", "zh-CN": "最终失败" },
  FRESH: { en: "FRESH", "zh-CN": "新鲜" },
  HISTORICAL_DATA_FUTURE_LEAK: { en: "HISTORICAL DATA FUTURE LEAK", "zh-CN": "历史数据未来泄漏" },
  IDENTITY_AMBIGUOUS: { en: "IDENTITY AMBIGUOUS", "zh-CN": "身份映射有歧义" },
  INSUFFICIENT_DATA: { en: "INSUFFICIENT DATA", "zh-CN": "数据不足" },
  LIVE_BASIC: { en: "LIVE BASIC", "zh-CN": "基础实时" },
  LIVE_DATA_DESYNC: { en: "LIVE DATA DESYNC", "zh-CN": "实时数据不同步" },
  LIVE_FULL: { en: "LIVE FULL", "zh-CN": "完整实时" },
  LIVE_STALE: { en: "LIVE STALE", "zh-CN": "实时数据过期" },
  LIVE_SYNC_UNKNOWN: { en: "LIVE SYNC UNKNOWN", "zh-CN": "实时同步未知" },
  MARKET_MISSING: { en: "MARKET MISSING", "zh-CN": "市场数据缺失" },
  MARKET_STALE: { en: "MARKET STALE", "zh-CN": "市场数据过期" },
  MISSING: { en: "MISSING", "zh-CN": "缺失" },
  NO_BUY: { en: "NO BUY", "zh-CN": "不买入" },
  NO_SNAPSHOT: { en: "NO SNAPSHOT", "zh-CN": "无快照" },
  PARSE_FAILED: { en: "PARSE FAILED", "zh-CN": "解析失败" },
  PARTIAL: { en: "PARTIAL", "zh-CN": "部分可用" },
  PENDING: { en: "PENDING", "zh-CN": "待处理" },
  POST_DRAFT: { en: "POST DRAFT", "zh-CN": "选人后" },
  PREMATCH: { en: "PREMATCH", "zh-CN": "赛前" },
  READY: { en: "READY", "zh-CN": "就绪" },
  RESTARTING: { en: "RESTARTING", "zh-CN": "重启中" },
  RETRY_WAIT: { en: "RETRY WAIT", "zh-CN": "等待重试" },
  ROSTER_IDENTITY_AMBIGUOUS: { en: "ROSTER IDENTITY AMBIGUOUS", "zh-CN": "阵容身份有歧义" },
  RUNNING: { en: "RUNNING", "zh-CN": "运行中" },
  SAFE: { en: "SAFE", "zh-CN": "安全" },
  STARTING: { en: "STARTING", "zh-CN": "启动中" },
  SUCCESS: { en: "SUCCESS", "zh-CN": "成功" },
  TIMEOUT: { en: "TIMEOUT", "zh-CN": "超时" },
  UNKNOWN: { en: "UNKNOWN", "zh-CN": "未知" },
  UNSAFE: { en: "UNSAFE", "zh-CN": "不安全" }
};

export function translateStatus(status: string, locale: Locale): string {
  const normalized = status.replaceAll(" ", "_");
  return statusMessages[normalized]?.[locale] ?? status.replaceAll("_", " ");
}

const dependencyMessages: Record<string, Record<Locale, string>> = {
  RAYBET_HTTP: { en: "RAYBET HTTP", "zh-CN": "RAYBET HTTP" },
  RAYBET_SOCKET: { en: "RAYBET SOCKET", "zh-CN": "RAYBET 实时" },
  DLTV_SOCKET: { en: "DLTV SOCKET", "zh-CN": "DLTV 实时" },
  DLTV_DRAFT: { en: "DLTV DRAFT", "zh-CN": "DLTV 选人" },
  LIVE_SYNC: { en: "LIVE SYNC", "zh-CN": "实时同步" },
  STRATZ: { en: "STRATZ", "zh-CN": "STRATZ" },
  DRAFT_ENGINE: { en: "DRAFT ENGINE", "zh-CN": "选人模型" },
  HISTORY: { en: "HISTORY", "zh-CN": "历史数据" },
  GPT: { en: "GPT", "zh-CN": "GPT" },
  CLAUDE: { en: "CLAUDE", "zh-CN": "CLAUDE" },
  GEMINI: { en: "GEMINI", "zh-CN": "GEMINI" }
};

export function translateDependency(name: string, locale: Locale): string {
  return dependencyMessages[name]?.[locale] ?? name.replaceAll("_", " ");
}
