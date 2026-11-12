import { Link, useParams } from "react-router";

import { endpoints } from "../api/endpoints";
import { AnalysisView } from "../components/analysis/AnalysisView";
import { ReportDownloads } from "../components/analysis/ReportDownloads";
import { ErrorNote, LinkButton, Loading, PageHeader } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { fmtInstant, fmtPeriod } from "../lib/format";

export default function AnalysisPage() {
  const analysisId = Number(useParams().analysisId);
  const analysis = useAsync((signal) => endpoints.analysis(analysisId, signal), [analysisId]);

  if (analysis.loading && !analysis.data) return <Loading label="Loading the analysis" />;
  if (analysis.error) return <ErrorNote error={analysis.error} onRetry={analysis.reload} />;
  if (!analysis.data) return null;
  const data = analysis.data;
  const result = data.result;

  return (
    <div>
      <PageHeader
        eyebrow={
          <>
            <Link to="/plants" className="underline underline-offset-2">Plants</Link> /{" "}
            <Link to={`/plants/${data.plant_id}`} className="underline underline-offset-2">{result.plant.name}</Link> /{" "}
            <Link to={`/datasets/${data.dataset_id}`} className="underline underline-offset-2">{data.dataset_name}</Link>
          </>
        }
        title={`Analysis ${data.id}`}
        description={
          <>
            {fmtPeriod(data.period_start, data.period_end)} · issued {fmtInstant(data.created_at)} · engine {data.engine_version} ·{" "}
            {data.context === "DEMONSTRATION" ? "demonstration evaluation" : "operational evaluation"}
          </>
        }
        actions={
          <>
            <ReportDownloads analysisId={data.id} />
            <LinkButton to={`/datasets/${data.dataset_id}`} size="sm">Run again with other assumptions</LinkButton>
          </>
        }
      />
      <AnalysisView result={result} analysisId={data.id} />
      <p className="mt-8 break-all font-mono text-xs text-ink-500">
        Dataset SHA-256 {data.dataset_sha256} · the result is stored as issued and is never recomputed.
      </p>
    </div>
  );
}
