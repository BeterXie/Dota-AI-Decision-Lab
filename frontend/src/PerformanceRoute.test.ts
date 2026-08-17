import { expect, test } from "vitest";
import { isAiPerformanceRoute } from "./App";


test("AI performance route predicate does not capture unrelated prefixes", () => {
  expect(isAiPerformanceRoute("/performance")).toBe(true);
  expect(isAiPerformanceRoute("/performance/model-1")).toBe(true);
  expect(isAiPerformanceRoute("/performancefoo")).toBe(false);
  expect(isAiPerformanceRoute("/performance-anything")).toBe(false);
});
