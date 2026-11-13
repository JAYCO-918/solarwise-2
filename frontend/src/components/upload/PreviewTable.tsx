import type { UploadPreview } from "../../api/types";
import type { MetadataForm } from "../../lib/metadata";
import { cx } from "../../lib/cx";
import { fmtNumber } from "../../lib/format";
import { Badge } from "../ui";
import { USE_STYLE, columnUse } from "./roles";

/**
 * The first rows of the file, cell by cell as they are in it, with what each column is used for as the mapping
 * stands. An empty cell is shown empty: it is "not observed", never a zero.
 */
export function PreviewTable({ preview, form }: { preview: UploadPreview; form: MetadataForm | null }) {
  const shown = preview.sample_rows.length;
  return (
    <div>
      <div className="overflow-x-auto border-y border-ink-200">
        <table className="min-w-full border-collapse text-sm" aria-label="First rows of the file">
          <thead>
            <tr className="bg-ink-50">
              <th scope="col" className="sticky left-0 z-10 w-12 border-b border-ink-200 bg-ink-50 px-3 py-2 text-left text-xs font-medium text-ink-500">Row</th>
              {preview.columns.map((column) => {
                const use = columnUse(form, column.name);
                return (
                  <th key={column.name} scope="col" className="border-b border-l border-ink-200 px-3 py-2 text-left align-top font-medium">
                    <span className="block whitespace-nowrap font-mono text-xs text-ink-900">{column.name}</span>
                    <Badge className={cx("mt-1 whitespace-nowrap", USE_STYLE[use.kind])}>
                      {use.label}{use.unit ? ` · ${use.unit}` : ""}
                    </Badge>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {preview.sample_rows.map((row, index) => (
              // Rows of a file have no identity but their position.
              <tr key={index} className="odd:bg-white even:bg-ink-50/40">
                <td className="sticky left-0 z-10 border-b border-ink-100 bg-inherit px-3 py-1.5 text-xs tabular-nums text-ink-500">
                  {preview.file_format === "CSV" ? index + 2 : index + 1}
                </td>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="max-w-xs truncate whitespace-nowrap border-b border-l border-ink-100 px-3 py-1.5 font-mono text-xs text-ink-800" title={cell}>
                    {cell === "" ? <span className="font-sans italic text-ink-400">empty</span> : cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="px-5 py-3 text-xs text-ink-600">
        {shown < preview.rows_total
          ? `The first ${shown} of ${fmtNumber(preview.rows_total)} rows, exactly as they are in the file.`
          : `All ${shown} rows, exactly as they are in the file.`}{" "}
        Row numbers are the ones the validation report uses. An empty cell means “not observed”: it is never read as zero.
        {preview.decimal_comma && " Decimal commas are read as decimal points (semicolon-separated file)."}
      </p>
    </div>
  );
}
