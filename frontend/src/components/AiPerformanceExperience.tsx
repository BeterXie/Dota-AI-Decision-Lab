import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAiReadiness } from "../performanceApi";
import { useI18n } from "../i18n";
import { AiPerformancePage } from "./AiPerformancePage";
import { DecisionReadinessPanel } from "./DecisionReadinessPanel";
import "./decision-readiness.css";

export function AiPerformanceExperience() {
  const { locale } = useI18n();
  const readiness = useQuery({
    queryKey: ["ai-performance", "readiness", 168],
    queryFn: () => fetchAiReadiness(168),
    staleTime: 30_000,
    refetchInterval: 60_000
  });

  return (
    <>
      <div className="performance-readiness-shell product-container">
        <DecisionReadinessPanel
          data={readiness.data}
          loading={readiness.isLoading}
          error={Boolean(readiness.error)}
          onRetry={() => void readiness.refetch()}
          locale={locale}
        />
      </div>
      <AiPerformancePage />
    </>
  );
}
