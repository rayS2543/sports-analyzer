import React from "react";
import { Routes, Route } from "react-router-dom";
import MatchesTable from "./components/MatchesTable";
import TeamPage from "./components/TeamPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<MatchesTable />} />
      <Route path="/team/:teamName" element={<TeamPage />} />
    </Routes>
  );
}