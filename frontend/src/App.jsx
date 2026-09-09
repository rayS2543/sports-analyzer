import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import MatchesTable from "./components/MatchesTable";
import StandingsTable from "./components/StandingsTable";
import TeamsGrid from "./components/TeamsGrid";

export default function App() {
  return (
    <BrowserRouter>
      <Navbar />
      <Routes>
        <Route path="/" element={<MatchesTable />} />
        <Route path="/standings" element={<StandingsTable />} />
        <Route path="/teams" element={<TeamsGrid />} />
      </Routes>
    </BrowserRouter>
  );
}
