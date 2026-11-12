import { useState } from "react";

import type { AnalysisResult } from "../../api/types";
import { TabPanel, Tabs } from "../ui";
import { AttributionPanel } from "./AttributionPanel";
import { DecisionPanel, GatesPanel } from "./DecisionPanel";
import { EconomicsPanel } from "./EconomicsPanel";
import { ExplanationPanel } from "./ExplanationPanel";
import { GapPanel } from "./GapPanel";
import { HypothesesPanel } from "./HypothesesPanel";
import { ProvenancePanel, StagesStrip } from "./ProvenancePanel";

const TABS = [
  { key: "decision", label: "Decision" },
  { key: "performance", label: "Performance" },
  { key: "attribution", label: "Attribution" },
  { key: "diagnosis", label: "Diagnosis" },
  { key: "economics", label: "Economics" },
  { key: "provenance", label: "Provenance and quality" },
  { key: "explanation", label: "Explanation" },
];

/**
 * One result of the engine. `analysisId` is `null` for advisory evaluations, which are not stored: they have no
 * report, no forecast and no rephrasing.
 */
export function AnalysisView({ result, analysisId }: { result: AnalysisResult; analysisId: number | null }) {
  const [tab, setTab] = useState("decision");
  return (
    <div>
      <div className="mb-6">
        <StagesStrip stages={result.stages} />
      </div>
      <Tabs items={TABS} active={tab} onChange={setTab} label="Parts of the analysis" />
      <TabPanel tab="decision" active={tab}>
        <div className="space-y-6">
          <DecisionPanel result={result} />
          <GatesPanel result={result} />
        </div>
      </TabPanel>
      <TabPanel tab="performance" active={tab}><GapPanel result={result} analysisId={analysisId} /></TabPanel>
      <TabPanel tab="attribution" active={tab}><AttributionPanel result={result} /></TabPanel>
      <TabPanel tab="diagnosis" active={tab}><HypothesesPanel result={result} /></TabPanel>
      <TabPanel tab="economics" active={tab}><EconomicsPanel result={result} /></TabPanel>
      <TabPanel tab="provenance" active={tab}><ProvenancePanel result={result} /></TabPanel>
      <TabPanel tab="explanation" active={tab}><ExplanationPanel result={result} analysisId={analysisId} /></TabPanel>
    </div>
  );
}
