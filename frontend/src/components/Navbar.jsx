import React from "react";
import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "Matches", end: true },
  { to: "/standings", label: "Standings" },
  { to: "/teams", label: "Teams" },
];

export default function Navbar() {
  return (
    <nav className="bg-gray-900/90 border-b border-gray-700 sticky top-0 z-10 backdrop-blur">
      <div className="max-w-7xl mx-auto px-8 py-4 flex items-center gap-8">
        <span className="text-xl font-bold text-white">⚽ Sports Analyzer</span>
        <div className="flex gap-2">
          {links.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-gray-300 hover:bg-gray-700 hover:text-white"
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  );
}
