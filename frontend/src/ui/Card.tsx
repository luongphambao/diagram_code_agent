import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

/** The base raised surface — gate cards, popovers, panels all sit on this.
 * --radius-md (6px), --ink-850 raised surface, --ink-700 hairline border. */
export default function Card({ className = "", children, ...rest }: CardProps) {
  return (
    <div className={`rounded-md border border-line bg-raised ${className}`} {...rest}>
      {children}
    </div>
  );
}
