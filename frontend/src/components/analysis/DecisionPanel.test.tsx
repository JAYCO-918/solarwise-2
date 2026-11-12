import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fixtures } from "../../test/fixtures";
import { DecisionPanel, GatesPanel } from "./DecisionPanel";

describe("the decision", () => {
  it("is marked simulated when it rests on demonstration data, and authorises nothing", () => {
    const analysis = fixtures.cleanNow();
    expect(analysis.result.recommendation).toMatchObject({ decision: "CLEAN_NOW", simulated: true, operational_authorization: false });
    render(<DecisionPanel result={analysis.result} />);
    expect(screen.getByText("SIMULATED DECISION.")).toBeInTheDocument();
    expect(screen.getByText("Simulated")).toBeInTheDocument();
    expect(screen.getByText("Clean now")).toBeInTheDocument();
    expect(screen.getByText("No operational authorisation.")).toBeInTheDocument();
    expect(screen.queryByText("Operational authorisation issued.")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: analysis.result.recommendation.headline })).toBeInTheDocument();
  });

  it("is not marked simulated when the server says it is not", () => {
    const analysis = fixtures.cleanNow();
    Object.assign(analysis.result.recommendation, { simulated: false, operational_authorization: true });
    render(<DecisionPanel result={analysis.result} />);
    expect(screen.queryByText("SIMULATED DECISION.")).not.toBeInTheDocument();
    expect(screen.queryByText("Simulated")).not.toBeInTheDocument();
    expect(screen.getByText("Operational authorisation issued.")).toBeInTheDocument();
  });

  it("shows the rule that produced it", () => {
    const analysis = fixtures.unprofitable();
    render(<DecisionPanel result={analysis.result} />);
    expect(screen.getByText("Monitor")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`rule ${analysis.result.recommendation.rule} `))).toBeInTheDocument();
  });
});

describe("the gates", () => {
  it("tell a gate that could not be evaluated from one that failed", () => {
    const analysis = fixtures.missingData();
    const gates = analysis.result.recommendation.gates;
    const count = (state: boolean | null) => gates.filter((gate) => gate.passed === state).length;
    expect(count(null)).toBeGreaterThan(0);
    expect(count(false)).toBeGreaterThan(0);

    render(<GatesPanel result={analysis.result} />);
    expect(screen.getByRole("heading", { name: `Gates: ${count(true)} of ${gates.length} passed` })).toBeInTheDocument();
    expect(screen.getAllByText("Not evaluated")).toHaveLength(count(null));
    expect(screen.getAllByText("Not passed")).toHaveLength(count(false));
    expect(screen.getAllByText("Passed")).toHaveLength(count(true));
  });

  it("show each gate with what it found", () => {
    const analysis = fixtures.unprofitable();
    render(<GatesPanel result={analysis.result} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(analysis.result.recommendation.gates.length);
    const failed = analysis.result.recommendation.gates.filter((gate) => gate.passed === false);
    expect(failed).toHaveLength(1);
    const row = items.find((item) => within(item).queryByText("Not passed"));
    expect(row).toBeDefined();
    expect(within(row!).getByText(failed[0]!.label)).toBeInTheDocument();
    expect(within(row!).getByText(failed[0]!.detail)).toBeInTheDocument();
  });
});
