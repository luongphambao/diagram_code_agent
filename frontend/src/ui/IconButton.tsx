import { forwardRef, type ButtonHTMLAttributes } from "react";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string; // required — icon-only controls must always have an accessible name
  active?: boolean;
  size?: "sm" | "md";
}

/**
 * Icon-only control (theme toggle, sidebar collapse, zoom, etc.). `label` is
 * mandatory and doubles as aria-label + title (tooltip).
 */
const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, active = false, size = "md", className = "", children, ...rest },
  ref,
) {
  const dim = size === "sm" ? "h-6 w-6" : "h-8 w-8";
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={`inline-flex ${dim} flex-shrink-0 items-center justify-center rounded-sm transition-colors ${
        active ? "bg-well text-accent-text" : "text-secondary hover:bg-well hover:text-fg"
      } ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
});

export default IconButton;
