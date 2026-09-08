import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import NavBar from "./components/NavBar";
import MatchesTable from "./components/MatchesTable";
import StandingsTable from "./components/StandingsTable";
import TeamsList from "./components/TeamsList";

export default function App() {
  return (
    <BrowserRouter>
      <NavBar />
      <Routes>
        <Route path="/" element={<MatchesTable />} />
        <Route path="/standings" element={<StandingsTable />} />
        <Route path="/teams" element={<TeamsList />} />
      </Routes>
    </BrowserRouter>
  );
}
