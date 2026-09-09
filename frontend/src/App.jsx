import React from "react";
import { Routes, Route } from "react-router-dom";
import Dashboard from "./components/Dashboard";
import MatchDetailPage from "./components/MatchDetailPage";
import PlayerDetailPage from "./components/PlayerDetailPage";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/match/:id" element={<MatchDetailPage />} />
        <Route path="/player/:id" element={<PlayerDetailPage />} />
      </Routes>
    </div>
  );
}
