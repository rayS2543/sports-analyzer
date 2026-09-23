import React from "react";
import { Link } from "react-router-dom";
import { useFavorites } from "../favorites";
import NewsFeed from "./NewsFeed";
import { PageShell, Section } from "./ui";

export default function FeedPage() {
  const { favorites } = useFavorites();
  const teamNames = favorites.map((f) => f.name);

  return (
    <PageShell back>
      <Section title="For you" aside={favorites.length ? `${favorites.length} team${favorites.length === 1 ? "" : "s"}` : null}>
        {favorites.length ? (
          <NewsFeed teams={teamNames} />
        ) : (
          <p className="text-sm text-muted py-2">
            Follow a team to see their news here.{" "}
            <Link to="/" className="text-accent hover:underline">
              Browse teams →
            </Link>
          </p>
        )}
      </Section>
    </PageShell>
  );
}
