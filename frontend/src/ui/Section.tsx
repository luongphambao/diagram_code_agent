import type { ReactNode } from "react";

/** The "<h4> + list" pattern repeated across every gate card, generalised
 * into one primitive (plan §F.5): a 2xs uppercase muted label, a hairline
 * rule, then the section body. */
export default function Section({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      <h4 className="label-caps mb-1.5 text-2xs font-semibold text-muted">{title}</h4>
      {children}
    </section>
  );
}
