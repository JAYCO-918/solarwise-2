import { useSearchParams } from "react-router";

import { PageHeader, TabPanel, Tabs } from "../components/ui";
import { CalculatorTab } from "./reference/CalculatorTab";
import { EconomicReferencesTab } from "./reference/EconomicReferencesTab";
import { FormatTab } from "./reference/FormatTab";
import { RulesTab } from "./reference/RulesTab";

const TABS = [
  { key: "rules", label: "Decision rules" },
  { key: "format", label: "Data format and provenance" },
  { key: "economic", label: "Economic references" },
  { key: "calculator", label: "Cleaning cost calculator" },
];

export default function ReferencePage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab = TABS.some((t) => t.key === requested) ? (requested as string) : "rules";
  return (
    <div>
      <PageHeader
        title="How SolarWise DZ decides"
        description="The rules, the data format and the references behind every result. Everything on this page is read from the running engine."
      />
      <Tabs items={TABS} active={tab} onChange={(key) => setParams({ tab: key }, { replace: true })} label="Reference sections" />
      <TabPanel tab="rules" active={tab}><RulesTab /></TabPanel>
      <TabPanel tab="format" active={tab}><FormatTab /></TabPanel>
      <TabPanel tab="economic" active={tab}><EconomicReferencesTab /></TabPanel>
      <TabPanel tab="calculator" active={tab}><CalculatorTab /></TabPanel>
    </div>
  );
}
