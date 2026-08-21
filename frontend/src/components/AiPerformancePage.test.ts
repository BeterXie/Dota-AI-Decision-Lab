import { describe, expect, it } from "vitest";

import type { AiExperimentIdentity } from "../performanceApi";
import { identityKey } from "./AiPerformancePage";

const identity: AiExperimentIdentity = {
  provider: "openai",
  model: "gpt-5.6-sol",
  prompt_version: "prompt-v1",
  decision_policy_version: "policy-v1",
  ai_view_version: "view-v1",
  execution_config_version: "openai:default:r1:lag120:prior10"
};

describe("AI performance experiment identity", () => {
  it("keeps execution configuration versions in separate rows", () => {
    const changed = {
      ...identity,
      execution_config_version: "openai:default:r2:lag120:prior10"
    };

    expect(identityKey(identity)).not.toBe(identityKey(changed));
  });
});
