/**
 * A corrected fork of @copilotkit/react-core/v2's useHumanInTheLoop, for the
 * ONE case it doesn't support: a wildcard (`name: "*"`) HITL registration.
 *
 * Bug found live (Stage 3 Playwright verification against the real backend):
 * every resolved gate card rendered "Resolved *" instead of its real label
 * ("Tech Stack Recommendation", etc). Root cause, confirmed by reading
 * CopilotKit/packages/react-core/src/v2/hooks/use-human-in-the-loop.tsx:63-94 —
 * its render wrapper unconditionally overwrites `name`/`description` on the
 * props it hands to your render component with the REGISTRATION's static
 * `tool.name`/`tool.description`, not the actual tool call's name. That's
 * correct for the normal case (a specific-named registration IS the tool
 * call's name), but for a wildcard registration `tool.name` is literally
 * `"*"` — so every wildcard-rendered card gets `name: "*"` clobbering the
 * real gate type, no matter which of the 13 backend gates actually fired.
 *
 * This fork is identical to the library version except it does NOT
 * overwrite `name`/`description` — it passes the incoming `props.name`
 * (the real tool call name, verified via use-render-tool-call.tsx: `name:
 * toolName` where `toolName = toolCall.function.name`) straight through.
 * Delete this file in Stage 4 once the wildcard registration is replaced by
 * 13 real per-gate-name registrations, where the library's own
 * `useHumanInTheLoop` works correctly and this workaround is no longer needed.
 */
import { useCallback, useEffect, useRef } from "react";
import React from "react";
import { useFrontendTool, useCopilotKit } from "@copilotkit/react-core/v2";
import type { ReactFrontendTool, ReactToolCallRenderer } from "@copilotkit/react-core/v2";
import { ToolCallStatus } from "@copilotkit/core";

export interface WildcardHumanInTheLoopTool<T extends Record<string, unknown> = Record<string, unknown>> {
  name: string; // must be "*"
  description?: string;
  agentId?: string;
  render: React.ComponentType<
    | { name: string; description: string; toolCallId: string; agentId?: string; args: Partial<T>; status: ToolCallStatus.InProgress; result: undefined; respond: undefined }
    | { name: string; description: string; toolCallId: string; agentId?: string; args: T; status: ToolCallStatus.Executing; result: undefined; respond: (result: unknown) => Promise<void> }
    | { name: string; description: string; toolCallId: string; agentId?: string; args: T; status: ToolCallStatus.Complete; result: string; respond: undefined }
  >;
}

export function useWildcardHumanInTheLoop<T extends Record<string, unknown> = Record<string, unknown>>(
  tool: WildcardHumanInTheLoopTool<T>,
) {
  const { copilotkit } = useCopilotKit();
  const resolvePromiseRef = useRef<((result: unknown) => void) | null>(null);
  const cleanupAbortRef = useRef<(() => void) | null>(null);

  const respond = useCallback(async (result: unknown) => {
    if (resolvePromiseRef.current) {
      cleanupAbortRef.current?.();
      cleanupAbortRef.current = null;
      resolvePromiseRef.current(result);
      resolvePromiseRef.current = null;
    }
  }, []);

  const handler = useCallback(async (_args: T, context?: { signal?: AbortSignal }) => {
    const signal = context?.signal;
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new Error("Human-in-the-loop interaction aborted"));
        return;
      }
      resolvePromiseRef.current = resolve;
      if (signal) {
        const onAbort = () => {
          cleanupAbortRef.current = null;
          resolvePromiseRef.current = null;
          reject(new Error("Human-in-the-loop interaction aborted"));
        };
        signal.addEventListener("abort", onAbort, { once: true });
        cleanupAbortRef.current = () => signal.removeEventListener("abort", onAbort);
      }
    });
  }, []);

  const RenderComponent: ReactToolCallRenderer<T>["render"] = useCallback(
    (props) => {
      const ToolComponent = tool.render;
      // `description` isn't part of the base renderer props at all (only
      // name/toolCallId/args/status/result are) — that part of the library
      // wrapper's behavior is legitimate, so it's added from the
      // registration here same as upstream. The ONE deliberate deviation is
      // `name`: kept as `props.name` (the REAL tool call name) instead of
      // being overwritten with `tool.name` (which would be the literal "*").
      if (props.status === ToolCallStatus.InProgress) {
        return React.createElement(ToolComponent, {
          ...props,
          description: tool.description || "",
          agentId: tool.agentId,
          respond: undefined,
        });
      } else if (props.status === ToolCallStatus.Executing) {
        return React.createElement(ToolComponent, {
          ...props,
          description: tool.description || "",
          agentId: tool.agentId,
          respond,
        });
      } else if (props.status === ToolCallStatus.Complete) {
        return React.createElement(ToolComponent, {
          ...props,
          description: tool.description || "",
          agentId: tool.agentId,
          respond: undefined,
        });
      }
      const exhaustiveCheck: never = props;
      return exhaustiveCheck;
    },
    [tool.render, tool.description, tool.agentId, respond],
  );

  const frontendTool: ReactFrontendTool<T> = {
    name: tool.name,
    description: tool.description,
    agentId: tool.agentId,
    handler,
    render: RenderComponent,
  };

  useFrontendTool(frontendTool);

  // Mirrors the library version: HITL renderers remove themselves on
  // unmount since they can no longer respond to user interaction.
  useEffect(() => {
    return () => copilotkit.removeHookRenderToolCall(tool.name, tool.agentId);
  }, [copilotkit, tool.name, tool.agentId]);
}
