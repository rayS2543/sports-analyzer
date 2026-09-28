import React, { Suspense, lazy } from "react";
import { Routes, Route } from "react-router-dom";
import Dashboard from "./components/Dashboard";
import FeedPage from "./components/FeedPage";
import MatchDetailPage from "./components/MatchDetailPage";
import PlayerDetailPage from "./components/PlayerDetailPage";
import TeamDetailPage from "./components/TeamDetailPage";
import { FavoritesProvider } from "./favorites";

// Lazy so three.js only loads when someone opens the VAR room.
const VarPage = lazy(() => import("./components/var/VarPage"));

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
          <Route
            path="/var"
            element={
              <Suspense fallback={null}>
                <VarPage />
              </Suspense>
            }
          />
        </Routes>
      </div>
    </FavoritesProvider>
  );
}
