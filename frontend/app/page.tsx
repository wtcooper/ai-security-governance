import Link from "next/link";
import { ArrowRight, CircleCheck, CircleX } from "lucide-react";
import { fetchGatewayStatus, fetchModels, type AssetType } from "@/lib/api";
import { ASSET } from "./ui/vocabulary";

const ORDER: AssetType[] = ["llm", "mcp", "skill"];

export default async function Home() {
  const [gateway, models] = await Promise.all([fetchGatewayStatus(), fetchModels()]);

  return (
    <div className="space-y-12">
      <section className="max-w-2xl space-y-3">
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight">
          Evaluate an AI asset
        </h1>
        <p className="text-[13.5px] leading-relaxed text-muted">
          Determines whether an asset clears our security thresholds and can be auto-approved,
          or whether it needs formal deep testing. Every result is measured against a written
          threshold and records which models and which policy produced it.
        </p>
      </section>

      <section>
        <h2 className="eyebrow mb-3">Choose an asset class</h2>
        <div className="grid gap-px overflow-hidden rounded-card border border-rule bg-rule sm:grid-cols-3">
          {ORDER.map((slug) => {
            const asset = ASSET[slug];
            const Icon = asset.icon;
            return (
              <Link
                key={slug}
                href={`/evaluate/${slug}`}
                className="group flex flex-col gap-3 bg-surface p-5 transition-colors hover:bg-paper"
              >
                <Icon size={18} strokeWidth={1.75} className="text-ink" aria-hidden="true" />
                <div className="space-y-1.5">
                  <h3 className="text-[14px] font-medium">{asset.label}</h3>
                  <p className="text-[12px] leading-relaxed text-muted">{asset.blurb}</p>
                </div>
                <span className="mt-auto flex items-center gap-1 text-[12px] font-medium text-ink">
                  Evaluate
                  <ArrowRight
                    size={13}
                    className="transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </span>
              </Link>
            );
          })}
        </div>
      </section>

      <GatewayPanel gateway={gateway} models={models} />
    </div>
  );
}

function GatewayPanel({
  gateway,
  models,
}: {
  gateway: Awaited<ReturnType<typeof fetchGatewayStatus>>;
  models: string[] | null;
}) {
  // The gateway is the single dependency every compute engine shares, so its state is on the
  // landing page rather than buried — one red line here explains every downstream failure.
  const reachable = gateway?.ok ?? false;
  const StatusIcon = reachable ? CircleCheck : CircleX;

  return (
    <section className="rounded-card border border-rule bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-5 py-3">
        <h2 className="eyebrow">Model gateway</h2>
        <span
          className={`flex items-center gap-1.5 text-[12px] font-medium ${
            reachable ? "text-pass" : "text-block"
          }`}
        >
          <StatusIcon size={13} aria-hidden="true" />
          {reachable ? "Reachable" : "Unreachable"}
        </span>
      </div>

      <div className="space-y-3 px-5 py-4">
        {gateway ? (
          <p className="tnum text-[12px] text-muted">{gateway.base_url}</p>
        ) : (
          <p className="text-[12px] text-block">
            The backend did not respond. Check that the API is running on port 8000.
          </p>
        )}

        {models === null ? (
          <p className="text-[12px] text-warn">
            Could not list models. Every evaluation runs through this gateway, so nothing will
            run until it is reachable.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {models.map((model) => (
              <span
                key={model}
                className="tnum rounded border border-rule px-1.5 py-0.5 text-[11px] text-muted"
              >
                {model}
              </span>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
