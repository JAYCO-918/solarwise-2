import { AlertTriangle, Info } from "lucide-react";

import type { DataNote } from "../../api/types";
import { Button } from "../ui";

/**
 * What the server's reader noticed in the values: units that do not fit, odd patterns, what the file lacks.
 * Deterministic - fixed thresholds, no model. A suggested unit is offered as a button; nothing is applied on its own.
 */
export function DataNotes({ notes, canUseUnit, onUseUnit }: {
  notes: DataNote[];
  /** Whether the column of the note is assigned to a quantity whose unit can be changed. */
  canUseUnit: (note: DataNote) => boolean;
  onUseUnit: (note: DataNote) => void;
}) {
  if (notes.length === 0) return null;
  const warnings = notes.filter((note) => note.severity === "WARNING");
  const information = notes.filter((note) => note.severity !== "WARNING");
  return (
    <div className="border-t border-ink-100 px-5 py-4">
      <h3 className="text-sm font-semibold text-ink-900">
        What the reader noticed
        <span className="ml-2 font-normal text-ink-500">
          {warnings.length > 0 ? `${warnings.length} to check` : "nothing to check"} · fixed rules, no language model
        </span>
      </h3>
      <ul className="mt-3 space-y-2">
        {[...warnings, ...information].map((note) => (
          <li key={`${note.code}-${note.column ?? ""}`} className="flex items-start gap-2.5 text-sm">
            {note.severity === "WARNING"
              ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700" aria-hidden />
              : <Info className="mt-0.5 size-4 shrink-0 text-ink-400" aria-hidden />}
            <div className="min-w-0">
              <p className={note.severity === "WARNING" ? "text-ink-900" : "text-ink-700"}>
                <span className="sr-only">{note.severity === "WARNING" ? "To check: " : "For information: "}</span>
                {note.message}
              </p>
              {note.suggested_unit && canUseUnit(note) && (
                <Button size="sm" className="mt-1.5" onClick={() => onUseUnit(note)}>
                  Use {note.suggested_unit} for “{note.column}”
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
