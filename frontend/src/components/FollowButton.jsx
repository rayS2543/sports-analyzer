import React from "react";
import { useFavorites } from "../favorites";

export default function FollowButton({ league, name }) {
  const { isFavorite, toggleFavorite } = useFavorites();
  const following = isFavorite(league, name);

  return (
    <button
      type="button"
      onClick={() => toggleFavorite(league, name)}
      aria-pressed={following}
      className={`pressable inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-inset ${
        following ? "bg-accent/15 text-accent ring-accent/30" : "text-muted ring-line hover:bg-surface"
      }`}
    >
      <span aria-hidden="true">{following ? "★" : "☆"}</span>
      {following ? "Following" : "Follow"}
    </button>
  );
}
