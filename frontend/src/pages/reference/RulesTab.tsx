import { endpoints } from "../../api/endpoints";
import { DecisionBadge } from "../../components/badges";
import { Card, CardHeader, ErrorNote, Loading, Table, Td, Th } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { fmtNumber, humanize } from "../../lib/format";

export function RulesTab() {
  const rules = useAsync((signal) => endpoints.decisionRules(signal), []);
  if (rules.loading && !rules.data) return <Loading label="Loading the decision rules" />;
  if (rules.error) return <ErrorNote error={rules.error} onRetry={rules.reload} />;
  if (!rules.data) return null;
  const data = rules.data;
  return (
    <div className="space-y-6">
      <Card className="border-l-4 border-l-sun-500 px-5 py-4">
        <p className="text-base font-medium text-ink-950">{data.principle}</p>
        <p className="mt-1 text-sm text-ink-600">
          Engine version {data.engine_version}. This page is produced by the engine itself: it describes the rules that
          actually run, not a separate document.
        </p>
      </Card>

      <Card aria-labelledby="rules-title">
        <CardHeader id="rules-title" title="Rules, in order" description="The first rule whose condition holds gives the decision. A language model is never involved." />
        <Table>
          <thead><tr><Th>Rule</Th><Th>Decision</Th><Th>Applies when</Th><Th>Why</Th></tr></thead>
          <tbody>
            {data.rules.map((rule) => (
              <tr key={rule.id}>
                <Td className="font-mono font-medium">{rule.id}</Td>
                <Td><DecisionBadge decision={rule.outcome} simulated={false} size="sm" /></Td>
                <Td className="max-w-md">{rule.applies_when}</Td>
                <Td className="max-w-md text-ink-700">{rule.rationale}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card aria-labelledby="gates-title">
        <CardHeader id="gates-title" title={`The ${data.gates.length} gates of “clean now”`} description="A cleaning is recommended only when every one of them is satisfied. Each analysis shows which gates passed and which did not." />
        <ol className="divide-y divide-ink-100">
          {data.gates.map((gate, index) => (
            <li key={gate.id} className="grid gap-1 px-5 py-3 sm:grid-cols-[2.5rem_minmax(0,1fr)]">
              <span className="tabular text-sm font-semibold text-ink-500">{index + 1}</span>
              <div>
                <p className="font-medium text-ink-950">{gate.label}</p>
                <p className="mt-0.5 text-sm text-ink-700">{gate.requirement}</p>
                <p className="mt-0.5 font-mono text-xs text-ink-500">{gate.id}</p>
              </div>
            </li>
          ))}
        </ol>
      </Card>

      <Card aria-labelledby="thresholds-title">
        <CardHeader id="thresholds-title" title="Thresholds" description="Engineering thresholds used by the rules. They are conventions of this tool, recorded with every analysis; they are not regulatory values." />
        <Table>
          <thead><tr><Th>Threshold</Th><Th numeric>Value</Th><Th>Meaning</Th></tr></thead>
          <tbody>
            {data.thresholds.map((threshold) => (
              <tr key={threshold.name}>
                <Td>
                  <span className="font-medium">{humanize(threshold.name)}</span>
                  <span className="block font-mono text-xs text-ink-500">{threshold.name}</span>
                </Td>
                <Td numeric>{fmtNumber(threshold.default, Number.isInteger(threshold.default) ? 0 : 3)}</Td>
                <Td className="max-w-xl text-ink-700">{threshold.description}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
