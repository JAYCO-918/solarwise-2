import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { setSession } from "../api/client";
import { App } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { fixtures } from "../test/fixtures";
import { TOKEN, apiError, json, mockApi } from "../test/http";
import type { RecordedCall } from "../test/http";

const ENGINEER = { id: 4, email: "engineer@example.org", full_name: "Engineer", role: "ENGINEER", is_active: true, is_demo: false };
const PLANT = { ...fixtures.plant(), id: 3, name: "Plant with its own export", is_demonstration: false, role: "OWNER" };
const FILE = () => new File(["Date,Energy (kWh)\n2026-05-01,46000\n"], "may-2026-export.csv", { type: "text/csv" });
const STORED = { id: 41, kind: "PRODUCTION", name: "May 2026, operator export" };

function routes(extra: Record<string, Response | ((call: RecordedCall) => Response)> = {}, ai = false) {
  return {
    "GET /meta": json({ ...fixtures.meta(), demo_mode: false, ai: { enabled: ai, provider: ai ? "openai-compatible" : null, role: "" } }),
    "GET /auth/me": json(ENGINEER),
    "GET /plants/3": json(PLANT),
    "GET /reference/schema": json(fixtures.referenceSchema()),
    "POST /plants/3/datasets/preview": json(fixtures.uploadPreview()),
    "POST /plants/3/datasets/validate": json(fixtures.uploadCheck()),
    ...extra,
  };
}

function open(path = "/plants/3/upload") {
  setSession(TOKEN.access_token, TOKEN.expires_at);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

async function chooseFile() {
  await userEvent.upload(await screen.findByLabelText("CSV or JSON file"), FILE());
  await screen.findByRole("heading", { name: "2. What the file contains" });
}

/** The row of the mapping form that belongs to one quantity. */
function quantity(metric: string) {
  const title = document.getElementById(`channel-${metric}-title`);
  if (!title) throw new Error(`no row for ${metric}`);
  return within(title.closest("div.px-4") as HTMLElement);
}

function declared(call: RecordedCall) {
  return JSON.parse((call.body as FormData).get("metadata") as string) as {
    name: string; timestamp_column: string;
    channels: Record<string, { column: string; unit: string; provenance: string; source: string; reported_as?: string }>;
    events?: { cleaning_column: string | null; event_column: string | null; provenance: string; source: string };
  };
}

describe("the upload page, before a file is chosen", () => {
  it("says what a file may hold, which two columns are needed, and offers templates in CSV and JSON", async () => {
    mockApi(routes());
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Upload operational data" })).toBeInTheDocument();
    const what = within(screen.getByRole("region", { name: "What to upload" }));
    expect(what.getByText("Energy produced").parentElement).toHaveTextContent("needed");
    expect(what.getByText("Soiling ratio, or measured soiling loss").parentElement).toHaveTextContent("optional");
    expect(what.getByText("Equipment alarms and operational events").parentElement).toHaveTextContent("optional");
    const templates = within(screen.getByRole("list", { name: "Templates and examples" }));
    expect(templates.getAllByRole("button").map((b) => b.textContent?.trim())).toEqual(["CSV template", "CSV example", "JSON template", "JSON example"]);
    expect(templates.getByText(/describe no real installation/)).toBeInTheDocument();
    // Nothing about the mapping or the check is shown before there is a file.
    expect(screen.queryByRole("heading", { name: "3. What each column is" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check the file" })).not.toBeInTheDocument();
  });
});

describe("a file that was chosen", () => {
  it("is shown as it is, with what each column was read as", async () => {
    const calls = mockApi(routes());
    open();
    await chooseFile();
    const sent = calls.find((c) => c.path === "/plants/3/datasets/preview");
    expect(((sent?.body as FormData).get("file") as File).name).toBe("may-2026-export.csv");
    expect((sent?.body as FormData).get("metadata")).toBeNull();  // a first look declares nothing

    const table = within(screen.getByRole("table", { name: "First rows of the file" }));
    const headers = table.getAllByRole("columnheader").slice(1).map((th) => th.textContent);
    expect(headers).toEqual([
      "DateDate and time", "Energy (kWh)Energy produced · kWh", "Expected production (kWh)Expected production · kWh",
      "Irradiance (W/m2)In-plane irradiation · W/m²", "Module temperature (°C)Module temperature · °C", "T2Not used",
      "Soiling loss (%)Soiling loss · %", "CleaningCleaning marks", "AlarmsAlarms and events", "OperatorNot used",
    ]);
    const rows = table.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(12);
    expect(within(rows[0]!).getAllByRole("cell").slice(0, 3).map((td) => td.textContent)).toEqual(["2", "2026-05-01", "46000.0"]);
    expect(within(rows[2]!).getAllByRole("cell")[2]).toHaveTextContent("abc");      // a wrong cell is shown as it is
    expect(within(rows[6]!).getAllByRole("cell")[2]).toHaveTextContent("empty");    // an empty cell is empty, not 0
    expect(screen.getByText(/The first 12 of 14 rows, exactly as they are in the file/)).toBeInTheDocument();
    expect(screen.getByText(/1 cell\(s\) of 'Energy \(kWh\)' are not numbers/)).toBeInTheDocument();
    expect(screen.getByText(/fixed rules, no language model/)).toBeInTheDocument();
  });

  it("pre-selects columns and units from the headers, and never a provenance", async () => {
    mockApi(routes());
    open();
    await chooseFile();
    expect(screen.getByRole("heading", { name: "Quantities (5 assigned)" })).toBeInTheDocument();
    const energy = quantity("actual_energy");
    expect(energy.getByLabelText("Column of the file")).toHaveValue("Energy (kWh)");
    expect(energy.getByLabelText("Unit in the file")).toHaveValue("kWh");
    expect(energy.getByText("Read from the header")).toBeInTheDocument();
    const soiling = quantity("soiling_ratio");
    expect(soiling.getByLabelText("Unit in the file")).toHaveValue("percent");
    expect(soiling.getByLabelText("What the column holds")).toHaveValue("LOSS");
    const irradiance = quantity("poa_irradiation");
    expect(irradiance.getByLabelText("Unit in the file")).toHaveValue("w/m2");
    expect(irradiance.getByText("Check")).toBeInTheDocument();  // the header does not name the plane
    expect(irradiance.getByText(/Read as the mean over each interval/)).toBeInTheDocument();
    expect(quantity("ambient_temp").getByLabelText("Column of the file")).toHaveValue("");
    for (const select of screen.getAllByLabelText("Provenance")) expect(select).toHaveValue("UNKNOWN");
    expect(screen.getByLabelText(/Column with cleaning marks/)).toHaveValue("Cleaning");
    expect(screen.getByLabelText(/Column with alarms or events/)).toHaveValue("Alarms");
    expect(screen.getByLabelText("Provenance of the events")).toHaveValue("UNKNOWN");
    expect(screen.getByText(/Columns not used:/)).toHaveTextContent("T2, Operator");
  });

  it("follows a correction by hand, in the form and above the preview", async () => {
    mockApi(routes());
    open();
    await chooseFile();
    await userEvent.selectOptions(quantity("ambient_temp").getByLabelText("Column of the file"), "T2");
    expect(screen.getByRole("heading", { name: "Quantities (6 assigned)" })).toBeInTheDocument();
    const header = within(screen.getByRole("table", { name: "First rows of the file" })).getAllByRole("columnheader")[6];
    expect(header).toHaveTextContent("T2Ambient temperature · °C");
    expect(quantity("ambient_temp").queryByText("Read from the header")).not.toBeInTheDocument();  // nobody proposed it
    await userEvent.selectOptions(quantity("soiling_ratio").getByLabelText("What the column holds"), "RATIO");
    expect(within(screen.getByRole("table", { name: "First rows of the file" })).getAllByRole("columnheader")[7]).toHaveTextContent("Soiling ratio · %");
  });

  it("offers the unit a note suggests, and applies it only when asked", async () => {
    const preview = fixtures.uploadPreview();
    preview.preview.notes.unshift({
      code: "LOOKS_LIKE_WH", severity: "WARNING", column: "Energy (kWh)", suggested_unit: "wh",
      message: "'Energy (kWh)' reaches 48,000,000 per interval, more than the plant can deliver. The values read as Wh.",
    });
    mockApi(routes({ "POST /plants/3/datasets/preview": json(preview) }));
    open();
    await chooseFile();
    expect(quantity("actual_energy").getByLabelText("Unit in the file")).toHaveValue("kWh");
    await userEvent.click(screen.getByRole("button", { name: "Use wh for “Energy (kWh)”" }));
    expect(quantity("actual_energy").getByLabelText("Unit in the file")).toHaveValue("wh");
    expect(screen.queryByRole("button", { name: "Use wh for “Energy (kWh)”" })).not.toBeInTheDocument();
  });

  it("is pointed out when the very same file was imported before", async () => {
    mockApi(routes({ "POST /plants/3/datasets/preview": json({ ...fixtures.uploadPreview(), same_file_as: [12] }) }));
    open();
    await chooseFile();
    expect(screen.getByText("This very file was already imported for this plant")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "dataset 12" })).toHaveAttribute("href", "/datasets/12");
  });

  it("is refused in the server's words when it cannot be read", async () => {
    mockApi(routes({ "POST /plants/3/datasets/preview": apiError(422, "UNREADABLE_FILE", "the file has a header but no data rows") }));
    open();
    await userEvent.upload(await screen.findByLabelText("CSV or JSON file"), FILE());
    expect(await screen.findByText(/the file has a header but no data rows/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "2. What the file contains" })).not.toBeInTheDocument();
  });
});

describe("the check", () => {
  it("sends the mapping with what the uploader declared, and shows events, rejections and what to do", async () => {
    const calls = mockApi(routes());
    open();
    await chooseFile();
    await userEvent.selectOptions(quantity("actual_energy").getByLabelText("Provenance"), "MEASURED");
    await userEvent.type(quantity("actual_energy").getByLabelText("Source"), "Revenue meter");
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    expect(await screen.findByText("The file can be imported")).toBeInTheDocument();

    const sent = declared(calls.find((c) => c.path === "/plants/3/datasets/validate")!);
    expect(sent.timestamp_column).toBe("Date");
    expect(sent.channels.actual_energy).toMatchObject({ column: "Energy (kWh)", unit: "kWh", provenance: "MEASURED", source: "Revenue meter" });
    expect(sent.channels.soiling_ratio).toMatchObject({ column: "Soiling loss (%)", unit: "percent", reported_as: "LOSS", provenance: "UNKNOWN" });
    expect(sent.channels.poa_irradiation).toMatchObject({ column: "Irradiance (W/m2)", unit: "w/m2", provenance: "UNKNOWN" });
    expect(sent.events).toEqual({ cleaning_column: "Cleaning", event_column: "Alarms", provenance: "UNKNOWN", source: "" });

    const report = within(screen.getByRole("region", { name: "4. Check, then import" }));
    expect(report.getByText("F-CLEAN-001")).toBeInTheDocument();
    expect(report.getByText("F-EVT-002").closest("tr")).toHaveTextContent("Inverter fault");
    expect(report.getByText("F-EVT-003").closest("tr")).toHaveTextContent("not used by the diagnosis");  // an alarm the vocabulary does not know
    expect(report.getAllByText(/What to do:/).length).toBeGreaterThan(2);
    expect(report.getByText(/These cells hold text where a number is expected/)).toBeInTheDocument();
    expect(report.getByRole("button", { name: /Rejected rows \(CSV\) · 2/ })).toBeEnabled();
    expect(report.getByRole("button", { name: /Validation report \(JSON\)/ })).toBeEnabled();
    expect(report.getByRole("button", { name: /Import and run the analysis/ })).toBeEnabled();
  });

  it("is needed again after any change of the mapping", async () => {
    mockApi(routes());
    open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    expect(await screen.findByText("The file can be imported")).toBeInTheDocument();
    await userEvent.selectOptions(quantity("ambient_temp").getByLabelText("Column of the file"), "T2");
    expect(screen.queryByText("The file can be imported")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Import and run the analysis/ })).not.toBeInTheDocument();
  });

  it("asks for the rejected rows with the declaration that was checked", async () => {
    const calls = mockApi(routes({
      "POST /plants/3/datasets/rejected-rows": new Response("solarwise_row,Date\n4,2026-05-03\n", {
        status: 200, headers: { "Content-Type": "text/csv", "Content-Disposition": 'attachment; filename="rejected-rows-may-2026-export.csv"' },
      }),
    }));
    URL.createObjectURL = () => "blob:rejected";
    URL.revokeObjectURL = () => {};
    open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    await userEvent.click(await screen.findByRole("button", { name: /Rejected rows \(CSV\)/ }));
    await waitFor(() => expect(calls.some((c) => c.path === "/plants/3/datasets/rejected-rows")).toBe(true));
    const asked = calls.find((c) => c.path === "/plants/3/datasets/rejected-rows")!;
    expect(declared(asked)).toEqual(declared(calls.find((c) => c.path === "/plants/3/datasets/validate")!));
  });

  it("points out a dataset that covers the same days, and refuses an exact duplicate", async () => {
    const overlapping = { ...fixtures.uploadCheck(), overlapping: [{ dataset_id: 9, name: "May, first export", period_start: "2026-05-01", period_end: "2026-05-30" }] };
    mockApi(routes({ "POST /plants/3/datasets/validate": json(overlapping) }));
    const view = open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    expect(await screen.findByText("Another dataset of this plant covers some of the same days")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "May, first export" })).toHaveAttribute("href", "/datasets/9");
    expect(screen.getByRole("button", { name: /Import and run the analysis/ })).toBeEnabled();  // a warning, not a refusal
    view.unmount();

    mockApi(routes({ "POST /plants/3/datasets/validate": json({ ...fixtures.uploadCheck(), duplicate_of: 12 }) }));
    open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    expect(await screen.findByText("Already imported")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Import and run the analysis/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Import the dataset" })).toBeDisabled();
  });
});

describe("the import", () => {
  const imported = () => ({ ...fixtures.uploadCheck(), stored: true, events_stored: 3, dataset: { ...STORED } });

  it("stores the file and runs the analysis on it", async () => {
    const analysis = { ...fixtures.missingData(), id: 77 };
    const calls = mockApi(routes({
      "POST /plants/3/datasets": json(imported(), 201),
      "POST /datasets/41/analyses": json(analysis, 201),
      "GET /analyses/77": json(analysis),
    }));
    open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    await userEvent.click(await screen.findByRole("button", { name: /Import and run the analysis/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Analysis 77" })).toBeInTheDocument();
    const order = calls.filter((c) => c.method === "POST").map((c) => c.path);
    expect(order).toEqual(["/plants/3/datasets/preview", "/plants/3/datasets/validate", "/plants/3/datasets", "/datasets/41/analyses"]);
    expect(calls.find((c) => c.path === "/datasets/41/analyses")?.body).toEqual({ options: {}, weather_dataset_id: null });
  });

  it("keeps the dataset and says why when the analysis cannot be run yet", async () => {
    mockApi(routes({
      "POST /plants/3/datasets": json(imported(), 201),
      "POST /datasets/41/analyses": apiError(422, "ANALYSIS_NOT_POSSIBLE", "no baseline is available for this dataset"),
    }));
    open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    await userEvent.click(await screen.findByRole("button", { name: /Import and run the analysis/ }));
    await waitFor(() => expect(screen.queryByRole("heading", { level: 1, name: "Upload operational data" })).not.toBeInTheDocument());
  });

  it("can stop at the dataset, without running anything", async () => {
    const calls = mockApi(routes({ "POST /plants/3/datasets": json(imported(), 201) }));
    open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    await userEvent.click(await screen.findByRole("button", { name: "Import the dataset" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/datasets/41")).toBe(true));
    expect(calls.some((c) => c.path === "/datasets/41/analyses")).toBe(false);
  });
});

describe("the AI assistant on the upload page", () => {
  it("is switched off without a language model, and the page says the reading is complete", async () => {
    const calls = mockApi(routes());
    open();
    await chooseFile();
    const assistant = within(screen.getByRole("region", { name: /Second reading by the AI assistant/ }));
    expect(assistant.getByRole("button", { name: /Ask the AI assistant/ })).toBeDisabled();
    expect(assistant.getByText(/No language model is configured on this server/)).toHaveTextContent("it is complete");
    expect(calls.some((c) => c.path.endsWith("/ai-review"))).toBe(false);
  });

  it("shows checked suggestions and applies one only when it is accepted", async () => {
    const calls = mockApi(routes({ "POST /plants/3/datasets/ai-review": json(fixtures.dataReview()) }, true));
    open();
    await chooseFile();
    const assistant = within(screen.getByRole("region", { name: /Second reading by the AI assistant/ }));
    expect(assistant.getByText(/never the file/)).toBeInTheDocument();
    await userEvent.click(assistant.getByRole("button", { name: /Ask the AI assistant/ }));
    const list = within(await assistant.findByRole("list", { name: "Suggestions of the AI assistant" }));
    expect(list.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Use T2 as Ambient temperature, in °C (now: not used)"),
      expect.stringContaining("Use Irradiance (W/m2) as Horizontal irradiation, in W/m² (now: in-plane irradiation, in W/m²)"),
    ]);
    expect(assistant.getByText(/example-model/)).toBeInTheDocument();
    expect(assistant.getByText(/2 proposal\(s\) of the assistant were discarded by the server's checks/)).toBeInTheDocument();
    expect(assistant.getByText(/to verify, nothing was changed/)).toBeInTheDocument();
    expect(((calls.find((c) => c.path.endsWith("/ai-review"))?.body as FormData).get("file") as File).name).toBe("may-2026-export.csv");

    // Nothing has moved yet.
    expect(quantity("ambient_temp").getByLabelText("Column of the file")).toHaveValue("");
    await userEvent.click(list.getByRole("button", { name: "Accept the suggestion for T2" }));
    const ambient = quantity("ambient_temp");
    expect(ambient.getByLabelText("Column of the file")).toHaveValue("T2");
    expect(ambient.getByLabelText("Unit in the file")).toHaveValue("degC");
    expect(ambient.getByText("Suggested by the AI assistant, accepted by you")).toBeInTheDocument();
    expect(ambient.getByLabelText("Provenance")).toHaveValue("UNKNOWN");  // where it comes from is still the uploader's to say
    expect(list.getByText("Accepted")).toBeInTheDocument();
    // The other suggestion was not accepted: the irradiance column is where the reader put it.
    expect(quantity("poa_irradiation").getByLabelText("Column of the file")).toHaveValue("Irradiance (W/m2)");
    expect(quantity("ghi").getByLabelText("Column of the file")).toHaveValue("");

    // What is accepted is sent to the same check as anything typed by hand.
    await userEvent.click(screen.getByRole("button", { name: "Check the file" }));
    await screen.findByText("The file can be imported");
    const sent = declared(calls.find((c) => c.path === "/plants/3/datasets/validate")!);
    expect(sent.channels.ambient_temp).toMatchObject({ column: "T2", unit: "degC", provenance: "UNKNOWN" });
  });

  it("says so when the model was asked and its answer could not be used", async () => {
    const failed = {
      ...fixtures.dataReview(), generated_by: "DETERMINISTIC_ENGINE", suggestions: [], observations: [], missing_context: [], discarded: [],
      fallback_reason: "the language-model provider did not answer within the time limit",
      notice: "A language model was asked, but its answer could not be used. The deterministic reading above stands.",
    };
    mockApi(routes({ "POST /plants/3/datasets/ai-review": json(failed) }, true));
    open();
    await chooseFile();
    await userEvent.click(screen.getByRole("button", { name: /Ask the AI assistant/ }));
    expect(await screen.findByText("No suggestion from a language model")).toBeInTheDocument();
    expect(screen.getByText(/did not answer within the time limit/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Suggestions of the AI assistant" })).not.toBeInTheDocument();
  });
});
