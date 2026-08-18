import React from "react";
import { AiPerformancePage } from "./AiPerformancePage";

export function AiPerformanceExperience() {
  // The performance page owns the first-screen hierarchy. The readiness and
  // benchmark panels used to render here as a second, full report above it,
  // which duplicated the data and made the route thousands of pixels tall.
  return <AiPerformancePage />;
}
