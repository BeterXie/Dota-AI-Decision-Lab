import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAiBenchmark } from "../benchmarkApi";
import { fetchAiReadiness } from "../performanceApi";
import { useI18n } from "../i18n";
import { AiPerformancePage } from "./AiPerformancePage";
import { BaselineBenchmarkPanel } from "./BaselineBenchmarkPanel";
import { DecisionReadinessPanel } from "./DecisionReadinessPanel";
import "./baseline-benchmark.css";
import "./decision-readiness.css";

export function AiPerformanceExperience() {
  const { locale } = useI18n();
  const readiness = useQuery({
    queryKey: ["ai-performance", "readiness", 168],
    queryFn: () => fetchAiReadiness(168),
    staleTime: 30_000,
    refetchInterval: 60_000
  });
  const benchmark = useQuery({
    queryKey: ["ai-performance", "benchmark"],
    queryFn: fetchAiBenchmark,
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
        <BaselineBenchmarkPanel
          data={benchmark.data}
          loading={benchmark.isLoading}
          error={Boolean(benchmark.error)}
          onRetry={() => void benchmark.refetch()}
          locale={locale}
        />
      </div>
      <AiPerformancePage />
    </>
  );
}
