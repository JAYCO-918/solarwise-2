import type { ReactNode } from "react";

import { Brand } from "./Layout";

const PRINCIPLES = [
  ["A gap is not a diagnosis", "Lower production than expected is an observation. It never proves soiling by itself."],
  ["Every value has an origin", "Measured, modelled, synthetic or unknown - declared with the data and shown with every figure."],
  ["Rules decide, not a model", "Clean now, investigate or monitor comes from a deterministic rule engine with ten explicit gates."],
  ["Missing stays missing", "A value that was not observed is never replaced by zero and never interpolated."],
] as const;

/** The page a visitor sees before a session exists: what the application is, next to the form. */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <section className="flex flex-col justify-between bg-ink-900 px-6 py-10 text-white sm:px-12 lg:py-14">
        <Brand className="text-lg" />
        <div className="my-10 max-w-xl">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            Know why a solar plant under-performs before deciding to clean it.
          </h1>
          <p className="mt-4 text-ink-200">
            SolarWise DZ compares what a photovoltaic plant produced with what it should have produced, separates the
            causes that the data can establish from those they cannot, and tells whether a cleaning is justified - and
            on what evidence.
          </p>
          <dl className="mt-8 grid gap-5 sm:grid-cols-2">
            {PRINCIPLES.map(([title, text]) => (
              <div key={title} className="border-l-2 border-sun-400 pl-3">
                <dt className="font-medium">{title}</dt>
                <dd className="mt-1 text-sm text-ink-300">{text}</dd>
              </div>
            ))}
          </dl>
        </div>
        <p className="text-xs text-ink-400">
          Reference case: El Foulia, 300 MWp nominal, Guemar (El Oued), Algeria. Name, location and nominal capacity are
          public information; every technical parameter of the demonstration is an illustrative assumption.
        </p>
      </section>

      <main className="flex items-center justify-center px-6 py-10 sm:px-12">
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  );
}
