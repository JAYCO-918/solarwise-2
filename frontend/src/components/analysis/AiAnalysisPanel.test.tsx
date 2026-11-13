import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { setSession } from "../../api/client";
import { App } from "../../App";
import { AuthProvider } from "../../auth/AuthContext";
import { fixtures } from "../../test/fixtures";
import { TOKEN, json, mockApi } from "../../test/http";
import type { RecordedCall } from "../../test/http";

const ENGINEER = { id: 4, email: "engineer@example.org", full_name: "Engineer", role: "ENGINEER", is_active: true, is_demo: false };
const VIEWER = { ...ENGINEER, id: 5, role: "VIEWER" };

function meta(ai: boolean) {
  return { ...fixtures.meta(), demo_mode: true, ai: { enabled: ai, provider: ai ? "openai-compatible" : null, role: "" } };
}

/** Open the page of an analysis on its "AI analysis" tab. */
async function open(routes: Record<string, Response | ((call: RecordedCall) => Response)>, user: typeof ENGINEER = ENGINEER) {
  setSession(TOKEN.access_token, TOKEN.expires_at);
  const calls = mockApi({ "GET /auth/me": json(user), ...routes });
  render(
    <MemoryRouter initialEntries={["/analyses/7"]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole("tab", { name: "AI analysis" }));
  await screen.findByRole("heading", { name: "AI analysis of the findings" });
  return calls;
}

/** Who a section says wrote it: the text of the tag next to its heading. */
function sourceOf(title: string): string | null | undefined {
  return screen.getByRole("heading", { name: title, level: 3 }).nextElementSibling?.textContent;
}

/** The cards of the possible explanations, one per cause (not the evidence lists inside them). */
function causeCards(): HTMLElement[] {
  const region = screen.getByRole("region", { name: "Possible explanations of the deviation" });
  return [...region.querySelectorAll<HTMLElement>(":scope > ul > li")];
}

const missingData = () => ({ ...fixtures.missingData(), id: 7 });
const cleanNow = () => ({ ...fixtures.cleanNow(), id: 7 });

describe("the AI analysis tab without a language model", () => {
  const routes = () => ({
    "GET /meta": json(meta(false)),
    "GET /analyses/7": json(missingData()),
    "GET /analyses/7/insight": json(fixtures.insightEngine()),
  });

  it("says the deterministic fallback is active, and that it is complete", async () => {
    await open(routes());
    expect(screen.getByText("No language model is configured on this server")).toBeInTheDocument();
    expect(screen.getByText(/The deterministic fallback is active/)).toHaveTextContent("it is complete");
    expect(screen.getByText("Narrative assembled by the engine")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate the AI analysis/ })).toBeDisabled();
  });

  it("marks every section as the engine's", async () => {
    await open(routes());
    for (const title of ["Summary", "Plant performance", "Main anomalies", "Data quality", "Economic implications",
      "Why the engine decided this", "Gates behind the decision", "What would change the decision", "Recommended next steps",
      "Information that is missing", "Uncertainty and limitations"]) {
      expect(sourceOf(title), title).toBe("Engine");
    }
    expect(screen.queryByRole("heading", { name: "Checks applied to the model's text" })).not.toBeInTheDocument();
  });

  it("shows the engine's decision, its gates and the support it gave each explanation", async () => {
    await open(routes());
    const insight = fixtures.insightEngine().insight;
    const decision = within(screen.getByRole("region", { name: "The engine's decision" }));
    expect(decision.getByText(insight.decision.statement)).toBeInTheDocument();
    expect(decision.getByText("Engine")).toBeInTheDocument();
    expect(insight.decision.statement).toMatch(/^SIMULATED DECISION .*Investigate\.$/);
    const causes = within(screen.getByRole("region", { name: "Possible explanations of the deviation" }));
    expect(causeCards().map((li) => within(li).getByRole("heading", { level: 4 }).textContent)).toEqual(insight.causes.map((c) => c.title));
    expect(causes.getAllByText("Cannot be evaluated").length).toBeGreaterThan(0);
    expect(causes.queryByText("AI interpretation")).not.toBeInTheDocument();
    expect(screen.getByText(insight.executive_summary)).toBeInTheDocument();
    const gates = insight.gates.filter((g) => g.passed === false);
    for (const gate of gates) expect(screen.getByText(gate.label)).toBeInTheDocument();
  });

  it("still exports the operational report", async () => {
    URL.createObjectURL = () => "blob:report";
    URL.revokeObjectURL = () => {};
    const calls = await open({
      ...routes(),
      "GET /analyses/7/operational-report.pdf": new Response("%PDF-1.4", { status: 200, headers: { "Content-Type": "application/pdf" } }),
    });
    await userEvent.click(screen.getByRole("button", { name: "Operational report as PDF" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/analyses/7/operational-report.pdf")).toBe(true));
  });
});

describe("the AI analysis tab with a language model", () => {
  const routes = (extra: Record<string, Response | ((call: RecordedCall) => Response)> = {}) => ({
    "GET /meta": json(meta(true)),
    "GET /analyses/7": json(cleanNow()),
    "GET /analyses/7/insight": json(fixtures.insightAi()),
    ...extra,
  });

  it("names the model, and tells its narrative from the engine's results section by section", async () => {
    await open(routes());
    expect(screen.getByText("Narrative written by a language model")).toBeInTheDocument();
    expect(screen.getByText(/openai-compatible · example-model/)).toBeInTheDocument();
    expect(screen.getByText(/11 checks passed/)).toBeInTheDocument();
    for (const title of ["Summary", "Plant performance", "Main anomalies", "Data quality", "Economic implications",
      "Why the engine decided this", "Uncertainty and limitations"]) {
      expect(sourceOf(title), title).toBe("AI interpretation");
    }
    // What a model cannot write stays marked as the engine's, even on a page whose narrative is the model's.
    for (const title of ["Gates behind the decision", "What would change the decision", "Recommended next steps", "Information that is missing"]) {
      expect(sourceOf(title), title).toBe("Engine");
    }
    expect(within(screen.getByRole("region", { name: "The engine's decision" })).getByText("Engine")).toBeInTheDocument();
    expect(screen.queryByText("No language model is configured on this server")).not.toBeInTheDocument();
  });

  it("shows the decision exactly as the engine stated it", async () => {
    await open(routes());
    const insight = fixtures.insightAi().insight;
    const analysis = cleanNow();
    expect(insight.decision.value).toBe(analysis.result.recommendation.decision);
    const decision = within(screen.getByRole("region", { name: "The engine's decision" }));
    expect(decision.getByText("SIMULATED DECISION (demonstration, not an operational instruction): Clean now.")).toBeInTheDocument();
    expect(decision.getByText("Simulated")).toBeInTheDocument();
    expect(decision.getByText(new RegExp(`Rule ${analysis.result.recommendation.rule} · 10 of 10 gates passed`))).toBeInTheDocument();
  });

  it("puts the engine's summary and the model's reading of each explanation side by side", async () => {
    await open(routes());
    const soiling = fixtures.insightAi().insight.causes.find((c) => c.category === "SOILING")!;
    const card = within(screen.getByRole("heading", { name: "Soiling", level: 4 }).closest("li") as HTMLElement);
    expect(card.getByText("Strong support")).toBeInTheDocument();
    expect(card.getByText(soiling.engine_summary).previousElementSibling).toHaveTextContent("Engine");
    expect(card.getByText(soiling.interpretation!).previousElementSibling).toHaveTextContent("AI interpretation");
    expect(card.getByText(/Evidence held by the engine/)).toBeInTheDocument();
  });

  it("lists the checks the model's text went through", async () => {
    await open(routes());
    const checks = within(screen.getByRole("region", { name: "Checks applied to the model's text" }));
    expect(checks.getAllByRole("listitem")).toHaveLength(11);
    expect(checks.getByText("Soiling not asserted without measurement")).toBeInTheDocument();
    expect(checks.getByText("Figures from engine only")).toBeInTheDocument();
    expect(checks.getAllByText(/passed/i).length).toBeGreaterThan(0);
  });

  it("generates on request, once, and shows what came back", async () => {
    const calls = await open(routes({
      "GET /analyses/7/insight": json({ ...fixtures.insightEngine(), insight: { ...fixtures.insightAi().insight, generated_by: "DETERMINISTIC_ENGINE", provider: null, model: null, checks: [] } }),
      "POST /analyses/7/insight": json(fixtures.insightAi(), 201),
    }));
    expect(sourceOf("Summary")).toBe("Engine");
    await userEvent.click(screen.getByRole("button", { name: /Generate the AI analysis/ }));
    expect(await screen.findByText("Narrative written by a language model")).toBeInTheDocument();
    expect(sourceOf("Summary")).toBe("AI interpretation");
    expect(calls.filter((c) => c.method === "POST" && c.path === "/analyses/7/insight")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Generate again/ })).toBeEnabled();
  });

  it("says why when the model was asked and its answer was not used", async () => {
    const refused = fixtures.insightAi();
    Object.assign(refused.insight, {
      generated_by: "DETERMINISTIC_ENGINE",
      fallback_reason: "the model's answer was rejected: soiling_not_asserted_without_measurement (states soiling as a fact ('caused by soiling'))",
      checks: [{ name: "soiling_not_asserted_without_measurement", passed: false, detail: "states soiling as a fact" }],
    });
    await open(routes({ "GET /analyses/7/insight": json(refused) }));
    expect(screen.getByText("A language model was asked, and its answer was not used")).toBeInTheDocument();
    expect(screen.getByText(/soiling_not_asserted_without_measurement \(states soiling as a fact/)).toBeInTheDocument();
    expect(screen.getByText("Narrative assembled by the engine")).toBeInTheDocument();
    expect(sourceOf("Summary")).toBe("Engine");
    const failed = within(screen.getByRole("region", { name: "Checks applied to the model's text" })).getByText("Soiling not asserted without measurement");
    expect(failed.nextElementSibling).toHaveTextContent("failed");
  });

  it("lets a read-only account read, not generate", async () => {
    await open(routes(), VIEWER);
    expect(screen.getByText("Narrative written by a language model")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Operational report as PDF" })).toBeEnabled();
  });
});

describe("an evaluation that is not stored", () => {
  it("has no AI analysis tab: there is no analysis for an interpretation to refer to", async () => {
    const { AnalysisView } = await import("./AnalysisView");
    render(<AnalysisView result={fixtures.cleanNow().result} analysisId={null} />);
    expect(screen.getByRole("tab", { name: "Decision" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "AI analysis" })).not.toBeInTheDocument();
  });
});
