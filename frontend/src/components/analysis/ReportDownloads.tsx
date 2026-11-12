import { Download } from "lucide-react";
import { useState } from "react";

import { download } from "../../api/client";
import { toApiError } from "../../hooks/useAsync";
import { Button, ErrorNote } from "../ui";

const FORMATS = [
  { key: "pdf", label: "PDF" },
  { key: "html", label: "HTML" },
  { key: "csv", label: "CSV" },
  { key: "json", label: "JSON" },
] as const;

/** Reports are rendered by the server from the stored result; the browser only saves the file. */
export function ReportDownloads({ analysisId }: { analysisId: number }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  async function save(format: string) {
    setBusy(format);
    setError(null);
    try {
      await download(`/analyses/${analysisId}/report.${format}`, `solarwise-analysis-${analysisId}.${format}`);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="no-print">
      <div role="group" aria-label="Download the report" className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm text-ink-600">
          <Download className="size-4" aria-hidden /> Report
        </span>
        {FORMATS.map((format) => (
          <Button key={format.key} size="sm" busy={busy === format.key} disabled={busy !== null} onClick={() => save(format.key)}>
            {format.label}
          </Button>
        ))}
      </div>
      {error && <div className="mt-2"><ErrorNote error={error} /></div>}
    </div>
  );
}
