import { forwardRef, type ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hi disabled:bg-well disabled:text-muted",
  secondary:
    "border border-line bg-well text-fg hover:border-accent-hi/40 hover:bg-well disabled:text-muted",
  ghost: "text-secondary hover:bg-well hover:text-fg disabled:text-muted",
  danger:
    "border border-danger/30 bg-danger/10 text-danger-text hover:bg-danger/20 disabled:border-line disabled:bg-well disabled:text-muted",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-3.5 py-1.5 text-sm",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

/**
 * The one button primitive for the app — replaces the ad hoc `rounded-xl
 * bg-blue-600` / `bg-amber-700` buttons scattered across the 12 approval
 * cards and the toolbar (plan §F.5, §D.5). Radius is always --radius-sm;
 * nothing in this design system gets `rounded-xl`/`rounded-2xl`.
 */
const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className = "", disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-sm font-medium transition-colors disabled:cursor-not-allowed ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
      {...rest}
    />
  );
});

export default Button;
