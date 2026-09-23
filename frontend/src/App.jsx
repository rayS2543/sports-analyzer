import React from "react";
import { Routes, Route } from "react-router-dom";
import Dashboard from "./components/Dashboard";
import FeedPage from "./components/FeedPage";
import MatchDetailPage from "./components/MatchDetailPage";
import PlayerDetailPage from "./components/PlayerDetailPage";
import TeamDetailPage from "./components/TeamDetailPage";
import { FavoritesProvider } from "./favorites";

export default function App() {
  return (
    <FavoritesProvider>
      <div className="min-h-screen bg-canvas text-fg">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/feed" element={<FeedPage />} />
          <Route path="/match/:id" element={<MatchDetailPage />} />
          <Route path="/player/:id" element={<PlayerDetailPage />} />
          <Route path="/team/:league/:name" element={<TeamDetailPage />} />
        </Routes>
      </div>
    </FavoritesProvider>
  );
}
