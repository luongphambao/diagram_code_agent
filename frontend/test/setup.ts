import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView (used by GateFrame's open-focus
// effect); stub it so gate-card component tests don't need to know that.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
