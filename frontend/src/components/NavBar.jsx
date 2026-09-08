import React from "react";
import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "Matches", end: true },
  { to: "/standings", label: "Standings" },
  { to: "/teams", label: "Teams" },
];

export default function NavBar() {
  return (
    <nav className="bg-gray-900/80 border-b border-gray-700">
      <div className="max-w-7xl mx-auto px-8 py-4 flex gap-6">
        {links.map(({ to, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `text-lg font-semibold transition-colors ${
                isActive ? "text-blue-400" : "text-gray-300 hover:text-white"
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
