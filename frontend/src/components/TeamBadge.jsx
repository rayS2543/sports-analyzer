import React, { useEffect, useState } from "react";
import { cachedCrest, getTeams, rememberCrest } from "../teamAssets";

const SIZE_CLASSES = {
  sm: "w-6 h-6",
  md: "w-8 h-8",
  lg: "w-14 h-14",
  xl: "w-20 h-20",
};

export default function TeamBadge({ name, crest, league, size = "md" }) {
  const [resolved, setResolved] = useState(null);
  const [failed, setFailed] = useState([]);
  const sizeClasses = SIZE_CLASSES[size] || SIZE_CLASSES.md;
  const src = [cachedCrest(name), crest, resolved?.name === name && resolved.crest].find((url) => url && !failed.includes(url));

  useEffect(() => {
    if (crest || cachedCrest(name) || !league) return;
    let active = true;
    getTeams(league).then(() => {
      if (active) setResolved({ name, crest: cachedCrest(name) });
    }).catch(() => { /* The team name remains visible if the provider is unavailable. */ });
    return () => { active = false; };
  }, [name, crest, league]);

  if (!src) return <span className={`inline-block shrink-0 ${sizeClasses}`} title={`${name}: crest unavailable`} aria-hidden="true" />;
  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      title={name}
      loading="lazy"
      className={`inline-block object-contain shrink-0 ${sizeClasses}`}
      onLoad={() => rememberCrest(name, src)}
      onError={() => setFailed((urls) => [...urls, src])}
    />
  );
}
