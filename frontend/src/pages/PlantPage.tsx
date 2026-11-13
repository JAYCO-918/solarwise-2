import { Upload } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { endpoints } from "../api/endpoints";
import { SimulatedTag } from "../components/badges";
import { ErrorNote, LinkButton, Loading, Notice, PageHeader, TabPanel, Tabs } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { fmtNumber, fmtPower, plural } from "../lib/format";
import { ROLE_LABEL, canEdit } from "../lib/labels";
import { AccessTab } from "./plant/AccessTab";
import { DatasetsTab } from "./plant/DatasetsTab";
import { DescriptionTab } from "./plant/DescriptionTab";
import { DevicesTab } from "./plant/DevicesTab";
import { EvidenceTab } from "./plant/EvidenceTab";
import { ExternalDataTab } from "./plant/ExternalDataTab";

export default function PlantPage() {
  const plantId = Number(useParams().plantId);
  const plant = useAsync((signal) => endpoints.plant(plantId, signal), [plantId]);
  const [tab, setTab] = useState("data");

  if (plant.loading && !plant.data) return <Loading label="Loading the plant" />;
  if (plant.error) return <ErrorNote error={plant.error} onRetry={plant.reload} />;
  if (!plant.data) return null;
  const data = plant.data;

  const tabs = [
    { key: "data", label: "Data and analyses" },
    { key: "description", label: "Description" },
    { key: "devices", label: `Devices (${data.device_count})` },
    { key: "evidence", label: "Evidence" },
    { key: "external", label: "Typical year and weather" },
    ...(data.role === "OWNER" ? [{ key: "access", label: "Access" }] : []),
  ];

  return (
    <div>
      <PageHeader
        eyebrow={<Link to="/plants" className="underline underline-offset-2">Plants</Link>}
        title={<span className="inline-flex flex-wrap items-center gap-3">{data.name}{data.is_demonstration && <SimulatedTag size="md" />}</span>}
        description={
          <>
            {fmtPower(data.spec.capacity_dc_kwp, true)} · {fmtNumber(data.spec.latitude, 2)}°, {fmtNumber(data.spec.longitude, 2)}° ·{" "}
            {plural(data.dataset_count, "dataset")} · your access: {ROLE_LABEL[data.role] ?? data.role}
          </>
        }
        actions={
          canEdit(data.role) ? (
            <LinkButton to={`/plants/${data.id}/upload`} variant="primary">
              <Upload className="size-4" aria-hidden /> Upload operational data
            </LinkButton>
          ) : undefined
        }
      />
      {data.is_demonstration && (
        <Notice tone="simulated" className="mb-6" title="Demonstration plant">
          {data.description || "Its data are synthetic. Results are simulated and never authorise field work."}
        </Notice>
      )}
      <Tabs items={tabs} active={tab} onChange={setTab} label="Parts of the plant" />
      <TabPanel tab="data" active={tab}><DatasetsTab plant={data} /></TabPanel>
      <TabPanel tab="description" active={tab}><DescriptionTab plant={data} onChange={plant.setData} /></TabPanel>
      <TabPanel tab="devices" active={tab}><DevicesTab plant={data} /></TabPanel>
      <TabPanel tab="evidence" active={tab}><EvidenceTab plant={data} /></TabPanel>
      <TabPanel tab="external" active={tab}><ExternalDataTab plant={data} onChange={plant.setData} /></TabPanel>
      {data.role === "OWNER" && <TabPanel tab="access" active={tab}><AccessTab plant={data} /></TabPanel>}
    </div>
  );
}
