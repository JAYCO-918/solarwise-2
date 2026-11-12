import { LinkButton, PageHeader } from "../components/ui";

export function NotFoundPage() {
  return (
    <div>
      <PageHeader title="Page not found" description="The address does not correspond to anything in SolarWise DZ." />
      <LinkButton to="/plants" variant="primary">Go to the plants</LinkButton>
    </div>
  );
}
