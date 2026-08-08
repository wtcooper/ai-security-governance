import Link from "next/link";
import { fetchGatewayStatus, fetchModels } from "@/lib/api";

const ASSET_CLASSES = [
  {
    slug: "llm",
    title: "Foundation model",
    input: "A gateway model alias, or a Hugging Face repo for open weights",
    detail:
      "Five benchmark-level gates over CyberSecEval 4 and AgentDojo, plus supply-chain scan results for open weights.",
  },
  {
    slug: "mcp",
    title: "MCP server",
    input: "A GitHub repository or a zip upload",
    detail:
      "Full mcp-scanner analyzer sweep: static, behavioral, tool poisoning, prompt defense, dependency CVEs.",
  },
  {
    slug: "skill",
    title: "Agent skill",
    input: "A GitHub repository or a zip upload",
    detail:
      "Full skill-scanner sweep: YARA patterns, AST dataflow, LLM-as-judge, meta consensus.",
  },
] as const;

export default async function Home() {
  const [gateway, models] = await Promise.all([fetchGatewayStatus(), fetchModels()]);

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">Evaluate an AI asset</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          Determines whether an asset clears our security thresholds and can be auto-approved,
          or whether it needs formal deep testing. Security criteria only — harmful-content
          and compliance evaluation are handled separately.
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        {ASSET_CLASSES.map((asset) => (
          <Link
            key={asset.slug}
            href={`/evaluate/${asset.slug}`}
            className="group rounded-lg border border-edge bg-surface p-5 transition-colors hover:border-accent"
          >
            <h2 className="text-base font-medium group-hover:text-accent">{asset.title}</h2>
            <p className="mt-2 text-xs text-muted">{asset.input}</p>
            <p className="mt-3 text-xs leading-relaxed text-muted">{asset.detail}</p>
          </Link>
        ))}
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
  // The gateway is the single dependency every compute engine shares, so its state is
  // surfaced on the landing page rather than buried — a red panel here explains every
  // downstream failure at once.
  const reachable = gateway?.ok ?? false;

  return (
    <section className="rounded-lg border border-edge bg-surface p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Model gateway</h2>
        <span
          className={`rounded px-2 py-0.5 text-xs ${
            reachable ? "bg-pass/15 text-pass" : "bg-fail/15 text-fail"
          }`}
        >
          {reachable ? "reachable" : "unreachable"}
        </span>
      </div>

      {gateway ? (
        <p className="mt-2 font-mono text-xs text-muted">{gateway.base_url}</p>
      ) : (
        <p className="mt-2 text-xs text-fail">
          Backend did not respond. Is the API running on port 8000?
        </p>
      )}

      {models === null ? (
        <p className="mt-3 text-xs text-warn">
          Could not list models. Every evaluation runs through this gateway, so nothing will
          run until it is reachable.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {models.map((model) => (
            <span
              key={model}
              className="rounded border border-edge px-1.5 py-0.5 font-mono text-[11px] text-muted"
            >
              {model}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
