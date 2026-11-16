import { useEffect, useState } from "react";

export function useRoute(): [string, (to: string) => void] {
  const get = () => window.location.hash.replace(/^#/, "") || "/";
  const [route, setRoute] = useState(get);
  useEffect(() => {
    const on = () => setRoute(get());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [route, (to: string) => { window.location.hash = to; }];
}

export function navigate(to: string) {
  window.location.hash = to;
}
