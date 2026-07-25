import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom doesn't implement scrollIntoView (used by GateFrame's open-focus
// effect); stub it so gate-card component tests don't need to know that.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// @testing-library/react's auto-cleanup registers onto a GLOBAL `afterEach`
// (relies on globals:true); this project's vitest.config.ts sets
// `globals: false`, so without this explicit call every component test's
// rendered DOM leaks into the next test in the same file — e.g. two Gate
// cards both left mounted with role="group" makes a later
// `getByRole("group")` ambiguous.
afterEach(() => {
  cleanup();
});
