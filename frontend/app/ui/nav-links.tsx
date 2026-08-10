"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Primary navigation with an active state. A dark command bar gives no affordance for
 * "where am I" unless the current section says so itself, so each link claims the routes
 * that belong to its section.
 */
const LINKS: { href: string; label: string; claims: string[] }[] = [
  { href: "/", label: "Evaluate", claims: ["/evaluate", "/criteria"] },
  { href: "/evaluations", label: "Results", claims: ["/evaluations", "/runs"] },
  { href: "/benchmarks", label: "Benchmarks", claims: ["/benchmarks"] },
  { href: "/policies", label: "Policies", claims: ["/policies"] },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <>
      {LINKS.map(({ href, label, claims }) => {
        const active =
          href === "/"
            ? pathname === "/" || claims.some((c) => pathname.startsWith(c))
            : claims.some((c) => pathname.startsWith(c));
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
              active
                ? "bg-white/8 text-white"
                : "text-carbon-muted hover:text-carbon-ink"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </>
  );
}
