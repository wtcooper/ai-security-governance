/**
 * The visual vocabulary, defined once.
 *
 * Every asset class, decision state and severity gets exactly one icon and one colour, and
 * every page reads them from here. Defining them centrally is what makes consistency
 * structural rather than a thing to remember (acceptance criterion 7.3).
 *
 * Icons are from Lucide. They are semantic, never ornamental: each one disambiguates a state
 * the reader has to act on. Shields are reserved for decisions and appear once per page — a
 * shield next to every heading would say nothing.
 */

import {
  BadgeCheck,
  CircleAlert,
  CircleDashed,
  Cpu,
  Info,
  type LucideIcon,
  Puzzle,
  Server,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  TriangleAlert,
} from "lucide-react";
import type { AssetType } from "@/lib/api";

export type Tone = "pass" | "warn" | "block" | "neutral";

export const TONE_TEXT: Record<Tone, string> = {
  pass: "text-pass",
  warn: "text-warn",
  block: "text-block",
  neutral: "text-muted",
};

export const TONE_PANEL: Record<Tone, string> = {
  pass: "border-pass/30 bg-pass-wash",
  warn: "border-warn/30 bg-warn-wash",
  block: "border-block/30 bg-block-wash",
  neutral: "border-rule bg-surface",
};

/** One icon per asset class, chosen to be literal about what the thing is. */
export const ASSET: Record<AssetType, { icon: LucideIcon; label: string; blurb: string }> = {
  llm: {
    icon: Cpu,
    label: "Foundation model",
    blurb: "A gateway model alias, or a Hugging Face repo for open weights",
  },
  mcp: {
    icon: Server,
    label: "MCP server",
    blurb: "A GitHub repository or a zip upload",
  },
  skill: {
    icon: Puzzle,
    label: "Agent skill",
    blurb: "A GitHub repository or a zip upload",
  },
};

/** Decision states. The label always travels with the icon, so colour is never the only
 *  carrier of meaning (criterion 7.5). */
export const DECISION: Record<string, { icon: LucideIcon; label: string; tone: Tone }> = {
  auto_approve: { icon: ShieldCheck, label: "Auto-approve", tone: "pass" },
  needs_deep_testing: { icon: ShieldAlert, label: "Needs deep testing", tone: "warn" },
  error: { icon: ShieldX, label: "No decision", tone: "block" },
};

export const PENDING = { icon: CircleDashed, label: "Running", tone: "neutral" as Tone };

export const SEVERITY: Record<string, { icon: LucideIcon; tone: Tone; rank: number }> = {
  critical: { icon: CircleAlert, tone: "block", rank: 0 },
  high: { icon: TriangleAlert, tone: "block", rank: 1 },
  medium: { icon: TriangleAlert, tone: "warn", rank: 2 },
  low: { icon: Info, tone: "neutral", rank: 3 },
  info: { icon: Info, tone: "neutral", rank: 4 },
};

export const SEVERITY_ORDER = Object.keys(SEVERITY).sort(
  (a, b) => SEVERITY[a].rank - SEVERITY[b].rank,
);

export function decisionFor(decision: string | null, status: string) {
  if (status === "running" || status === "pending") return PENDING;
  return (decision && DECISION[decision]) || { ...PENDING, label: "No decision" };
}

/** Provenance of a score: harvested from someone else, or measured here. */
export const PROVENANCE_ICON: Record<string, LucideIcon> = {
  published: BadgeCheck,
  harvested: BadgeCheck,
  self_run: Cpu,
};
