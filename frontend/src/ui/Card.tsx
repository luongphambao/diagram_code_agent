import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

/** The base raised surface — gate cards, popovers, panels all sit on this.
 * --radius-md (6px), --ink-850 raised surface, --ink-700 hairline border.
 * forwardRef so gate cards (WildcardGateCard, and Stage 4's GateFrame) can
 * focus the card itself on open (plan §F.6: focus the frame, not the
 * approve button, since focusing a primary invites an accidental Enter). */
const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className = "", children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={`rounded-md border border-line bg-raised ${className}`} {...rest}>
      {children}
    </div>
  );
});

export default Card;
