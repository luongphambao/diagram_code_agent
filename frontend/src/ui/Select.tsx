import { forwardRef, type SelectHTMLAttributes } from "react";

/** The one <select> primitive — replaces the ad hoc `border-white/10 bg-white/5`
 * selects in App.tsx's header (diagram-kind / role pickers). */
const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className = "", children, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      className={`rounded-sm border border-line bg-well px-1.5 py-0.5 text-xs text-fg outline-none hover:border-accent-hi/40 focus-visible:border-accent-hi ${className}`}
      {...rest}
    >
      {children}
    </select>
  );
});

export default Select;
