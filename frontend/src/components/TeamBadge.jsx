import React, { useState } from "react";

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
  sm: "w-6 h-6 text-[9px]",
  md: "w-8 h-8 text-[10px]",
  lg: "w-14 h-14 text-sm",
  xl: "w-20 h-20 text-lg",
};

export default function TeamBadge({ name, tla, crest, size = "md" }) {
  const [imgFailed, setImgFailed] = useState(false);
  const sizeClasses = SIZE_CLASSES[size] || SIZE_CLASSES.md;

  if (crest && !imgFailed) {
    return (
      <img
        src={crest}
        alt=""
        title={name}
        loading="lazy"
        className={`inline-block object-contain shrink-0 ${sizeClasses}`}
        onError={() => setImgFailed(true)}
      />
    );
  }

  // Neutral monogram so a missing crest never reads as team colours.
  return (
    <span
      className={`inline-flex items-center justify-center rounded-md bg-raised ring-1 ring-inset ring-line font-semibold tracking-tight text-muted shrink-0 ${sizeClasses}`}
      title={name}
      aria-hidden="true"
    >
      {initialsFor(name, tla)}
    </span>
  );
}
