import React, { useState } from "react";
import MatchesTable from "./components/MatchesTable";

export default function App() {
  const [selectedLeague, setSelectedLeague] = useState("PD");

  return (
    <div>
      <MatchesTable league={selectedLeague} />
    </div>
  );
}