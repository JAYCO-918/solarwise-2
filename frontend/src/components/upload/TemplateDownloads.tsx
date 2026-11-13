import { FileDown } from "lucide-react";
import { useState } from "react";

import { download } from "../../api/client";
import type { UploadTemplate } from "../../api/types";
import { toApiError } from "../../hooks/useAsync";
import { Button, ErrorNote } from "../ui";

/** Templates (column names, no data) and examples (invented values that describe no real plant). */
export function TemplateDownloads({ templates }: { templates: UploadTemplate[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  async function save(name: string) {
    setBusy(name);
    setError(null);
    try {
      await download(`/reference/templates/${name}`, name);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(null);
    }
  }

  if (templates.length === 0) return null;
  return (
    <div>
      <ul className="grid gap-2 sm:grid-cols-2" aria-label="Templates and examples">
        {templates.map((template) => (
          <li key={template.name} className="flex items-start gap-3 rounded-md border border-ink-200 px-3 py-2.5">
            <Button size="sm" busy={busy === template.name} disabled={busy !== null} onClick={() => void save(template.name)}>
              <FileDown className="size-4" aria-hidden /> {template.title}
            </Button>
            <p className="min-w-0 text-xs text-ink-600">{template.description}</p>
          </li>
        ))}
      </ul>
      {error && <div className="mt-2"><ErrorNote error={error} /></div>}
    </div>
  );
}
