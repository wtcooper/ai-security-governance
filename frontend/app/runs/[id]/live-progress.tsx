"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Check, CircleDashed, Clock } from "lucide-react";
import { fetchRunProgress, type RunProgress } from "@/lib/api";

const POLL_MS = 8000;

/**
 * Live per-benchmark progress for a running run.
 *
 * Polls the backend (which reads the eval child's journal) and re-renders in place; when
 * the run stops being `running`, it refreshes the whole page so the verdict and gates
 * appear without anyone having to know to reload.
 */
export function LiveProgress({ runId, status }: { runId: number; status: string }) {
  const router = useRouter();
  const [progress, setProgress] = useState<RunProgress | null>(null);

  useEffect(() => {
    if (status !== "running" && status !== "pending") return;
    let cancelled = false;

    async function poll() {
      const latest = await fetchRunProgress(runId);
      if (cancelled) return;
      setProgress(latest);
      if (latest && latest.status !== "running" && latest.status !== "pending") {
        router.refresh();
      }
    }

    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runId, status, router]);

  if (status !== "running" && status !== "pending") return null;
  if (!progress || progress.benchmarks.length === 0) return null;

  const done = progress.benchmarks.filter((b) => b.state === "done").length;

  return (
    <div className="mt-4 space-y-1.5 border-t border-rule pt-3">
      <div className="eyebrow">
        Benchmark {Math.min(done + 1, progress.benchmarks.length)} of{" "}
        {progress.benchmarks.length}
      </div>
      <ul className="space-y-1">
        {progress.benchmarks.map((benchmark) => (
          <li
            key={benchmark.check_id}
            className="flex items-center gap-2 text-[12px]"
          >
            {benchmark.state === "done" ? (
              <Check size={13} strokeWidth={2.5} className="text-pass" aria-hidden="true" />
            ) : benchmark.state === "running" ? (
              <CircleDashed size={13} className="spinner text-ink" aria-hidden="true" />
            ) : (
              <Clock size={13} className="text-faint" aria-hidden="true" />
            )}
            <span
              className={`tnum ${benchmark.state === "queued" ? "text-faint" : "text-ink"}`}
            >
              {benchmark.check_id}
            </span>
            <span className="tnum ml-auto text-[11px] text-muted">
              {benchmark.state === "running" && benchmark.samples_completed != null
                ? `sample ${benchmark.samples_completed}/${benchmark.samples_planned ?? "?"}`
                : benchmark.state === "done"
                  ? `n=${benchmark.samples_planned ?? "?"}`
                  : `planned n=${benchmark.samples_planned ?? "?"}`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
