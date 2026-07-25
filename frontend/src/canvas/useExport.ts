import { useCallback } from "react";
import type { AgentState } from "../hooks/agent-utils";
import { EXPORTS, downloadExport, openInDrawio, type ExportDescriptor } from "./exports";

/** One handler surface over EXPORTS + the drawio special case, so
 * ArtifactTabs' toolbar/lightbox both build their button rows off the same
 * source of truth instead of duplicating enabled/onClick logic per button. */
export function useExport(agentState: AgentState) {
  const download = useCallback((id: ExportDescriptor["id"]) => {
    const d = EXPORTS.find((e) => e.id === id);
    if (d) downloadExport(d, agentState);
  }, [agentState]);

  const isAvailable = useCallback(
    (id: ExportDescriptor["id"]) => {
      const d = EXPORTS.find((e) => e.id === id);
      return d ? !!d.select(agentState) : false;
    },
    [agentState],
  );

  const openDrawio = useCallback(() => openInDrawio(agentState), [agentState]);

  const visibleExports = useMemo(() => EXPORTS.filter((d) => isAvailable(d.id) || d.id === "png" || d.id === "drawio"), [isAvailable]);

  return { exports: EXPORTS, visibleExports, download, isAvailable, openDrawio };
}
