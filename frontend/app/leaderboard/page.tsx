import { redirect } from "next/navigation";

/**
 * The route was renamed to /evaluations — "leaderboard" implied a ranking, which is the wrong
 * idea for a governance record. This keeps existing links and bookmarks working rather than
 * turning them into 404s, and preserves the asset-class query string.
 */
export default async function LeaderboardRedirect({
  searchParams,
}: {
  searchParams: Promise<{ type?: string }>;
}) {
  const { type } = await searchParams;
  redirect(type ? `/evaluations?type=${type}` : "/evaluations");
}
