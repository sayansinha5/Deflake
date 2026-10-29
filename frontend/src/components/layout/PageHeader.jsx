import { useEffect } from "react";

import { appName } from "../../lib/config";
import { useShell } from "./shell";

export function PageHeader({ title, crumbs = [] }) {
  const { setTitle } = useShell();
  const trailKey = JSON.stringify(crumbs);
  useEffect(() => {
    const trail = JSON.parse(trailKey);
    const names = trail.map((crumb) => crumb.label);
    names.push(title);
    setTitle(trail.length ? { crumbs: trail, title } : title);
    document.title = `${names.join(" · ")} · ${appName}`;
    return () => setTitle("");
  }, [setTitle, title, trailKey]);
  return null;
}
