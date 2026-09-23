import React, { createContext, useContext, useState } from "react";

const Context = createContext();
const STORAGE_KEY = "sa-favorites";

// Stored as "league:name" strings so the same team name in two leagues
// (rare, but possible) doesn't collide.
const keyOf = (league, name) => `${league}:${name}`;

function load() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export function FavoritesProvider({ children }) {
  const [favorites, setFavorites] = useState(load);

  function toggleFavorite(league, name) {
    setFavorites((old) => {
      const key = keyOf(league, name);
      const next = old.some((f) => keyOf(f.league, f.name) === key)
        ? old.filter((f) => keyOf(f.league, f.name) !== key)
        : [...old, { league, name }];
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }

  function isFavorite(league, name) {
    return favorites.some((f) => f.league === league && f.name === name);
  }

  return (
    <Context.Provider value={{ favorites, toggleFavorite, isFavorite }}>
      {children}
    </Context.Provider>
  );
}

export const useFavorites = () => useContext(Context);
