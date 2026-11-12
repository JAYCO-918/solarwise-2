import { MapPin, Plus } from "lucide-react";
import { Link } from "react-router";

import { endpoints } from "../api/endpoints";
import type { Plant } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DecisionBadge, SimulatedTag } from "../components/badges";
import { Card, EmptyState, ErrorNote, LinkButton, Loading, PageHeader } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { fmtInstant, fmtNumber, fmtPct, fmtPower, plural } from "../lib/format";
import { ROLE_LABEL } from "../lib/labels";

function PlantCard({ plant }: { plant: Plant }) {
  const latest = plant.latest_analysis;
  return (
    <Card as="article" className="flex flex-col">
      <div className="flex-1 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="text-lg font-semibold text-ink-950">
            <Link to={`/plants/${plant.id}`} className="hover:underline">{plant.name}</Link>
          </h2>
          {plant.is_demonstration && <SimulatedTag />}
        </div>
        <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-600">
          <MapPin className="size-3.5" aria-hidden />
          {fmtNumber(plant.spec.latitude, 2)}°, {fmtNumber(plant.spec.longitude, 2)}° · {plant.spec.timezone}
        </p>
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-500">Capacity</dt>
            <dd className="tabular font-medium">{fmtPower(plant.spec.capacity_dc_kwp, true)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-500">Datasets</dt>
            <dd className="tabular font-medium">{plant.dataset_count}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-500">Your access</dt>
            <dd className="font-medium">{ROLE_LABEL[plant.role] ?? plant.role}</dd>
          </div>
        </dl>
      </div>
      <div className="border-t border-ink-100 px-5 py-3 text-sm">
        {latest ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-ink-500">Latest analysis</span>
              <DecisionBadge decision={latest.decision} simulated={latest.simulated} size="sm" />
              <span className="tabular text-ink-600">gap {fmtPct(latest.window_gap_pct)}</span>
            </div>
            <Link to={`/analyses/${latest.id}`} className="font-medium text-ink-900 underline underline-offset-2">
              Open<span className="sr-only"> the latest analysis of {plant.name}</span>
            </Link>
          </div>
        ) : (
          <span className="text-ink-500">No analysis yet · {plural(plant.device_count, "device")} · updated {fmtInstant(plant.updated_at)}</span>
        )}
      </div>
    </Card>
  );
}

export function PlantsPage() {
  const { user, meta } = useAuth();
  const plants = useAsync((signal) => endpoints.plants(signal), []);
  const mayCreate = user !== null && user.role !== "VIEWER";
  // An account starts with an empty list while the examples live in the demonstration, which needs no account.
  const examplesElsewhere = meta?.demo_mode === true && user !== null && !user.is_demo;

  return (
    <div>
      <PageHeader
        title="Plants"
        description="Each plant has its description, its datasets, its evidence records and the analyses run on them."
        actions={mayCreate ? <LinkButton to="/plants/new" variant="primary"><Plus className="size-4" aria-hidden /> Register a plant</LinkButton> : undefined}
      />
      {plants.loading && <Loading label="Loading the plants" />}
      {plants.error && <ErrorNote error={plants.error} onRetry={plants.reload} />}
      {plants.data && plants.data.length === 0 && (
        <Card>
          <EmptyState title="No plant yet" action={mayCreate ? <LinkButton to="/plants/new" variant="primary">Register a plant</LinkButton> : undefined}>
            {mayCreate
              ? "Register a plant to upload its production data and run an analysis."
              : "No plant has been shared with your account. Ask an owner to give you access."}
            {examplesElsewhere && " The ten example scenarios are in the demonstration: sign out, then choose “Open the demonstration”."}
          </EmptyState>
        </Card>
      )}
      {plants.data && plants.data.length > 0 && (
        <div className="grid gap-5 md:grid-cols-2">
          {plants.data.map((plant) => <PlantCard key={plant.id} plant={plant} />)}
        </div>
      )}
    </div>
  );
}
