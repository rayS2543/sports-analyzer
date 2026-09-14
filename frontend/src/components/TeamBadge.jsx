import React, { useState } from "react";

const PALETTE = [
  "bg-rose-500",
  "bg-amber-500",
  "bg-emerald-500",
  "bg-sky-500",
  "bg-violet-500",
  "bg-fuchsia-500",
  "bg-orange-500",
  "bg-teal-500",
];

function colorFor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

function initialsFor(name, tla) {
  if (tla) return tla.slice(0, 3).toUpperCase();
  return name
    .split(" ")
    .map((word) => word[0])
    .join("")
    .slice(0, 3)
    .toUpperCase();
}

const SIZE_CLASSES = {
  sm: "w-7 h-7 text-[10px]",
  md: "w-9 h-9 text-xs",
  lg: "w-20 h-20 text-2xl",
};

export default function TeamBadge({ name, tla, crest, size = "md" }) {
  const [imgFailed, setImgFailed] = useState(false);
  const sizeClasses = SIZE_CLASSES[size] || SIZE_CLASSES.md;

  if (crest && !imgFailed) {
    return (
      <img
        src={crest}
        alt={name}
        title={name}
        className={`inline-block object-contain shrink-0 ${sizeClasses}`}
        onError={() => setImgFailed(true)}
      />
    );
  }

  return (
    <span
      className={`inline-flex items-center justify-center rounded-full font-bold text-white shrink-0 ${sizeClasses} ${colorFor(name)}`}
      title={name}
    >
      {initialsFor(name, tla)}
    </span>
  );
}
