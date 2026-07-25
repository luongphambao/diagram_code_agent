/**
 * <CopilotKitProvider properties={...}> only captures its initial value —
 * `CopilotKitCore` is constructed once behind a lazy ref
 * (CopilotKit/packages/react-core/src/v2/providers/CopilotKitProvider.tsx:
 * `if (!copilotkitRef.current) { ... new CopilotKitCore({ properties, ... }) }`)
 * and nothing re-reads the prop on later renders. Ongoing updates (userRole/
 * diagramKind changing, a file finishing upload) must go through the
 * imperative `copilotkit.setProperties(...)` (verified in
 * CopilotKit/packages/core/src/core/core.ts:788) instead — this component
 * is that sync point, mounted once inside the provider.
 */
import { useEffect } from "react";
import { useCopilotKit } from "@copilotkit/react-core/v2";

export interface DiagramForwardedProperties {
  file_ids: string[];
  userRole: string;
  diagramKind: string;
}

export default function PropertiesSync(properties: DiagramForwardedProperties) {
  const { copilotkit } = useCopilotKit();
  const { file_ids, userRole, diagramKind } = properties;

  useEffect(() => {
    copilotkit.setProperties({ file_ids, userRole, diagramKind });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [copilotkit, JSON.stringify(file_ids), userRole, diagramKind]);

  return null;
}
