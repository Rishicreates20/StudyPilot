import Link from "next/link";

import type { NavItem } from "@/lib/site";

/**
 * The header links before the current path is known.
 *
 * On a page whose address contains a parameter (a goal's ID), the path is only known when a
 * request arrives, so the interactive `NavLinks` (which highlights the current page) streams in
 * after the page shell. This renders the same links without the highlight meanwhile, so the
 * header never flashes empty.
 */
export function NavLinksFallback({ items }: { items: readonly NavItem[] }) {
  return (
    <ul className="flex flex-row items-center gap-1">
      {items.map((item) => (
        <li key={item.href}>
          <Link
            href={item.href}
            className="block rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            {item.label}
          </Link>
        </li>
      ))}
    </ul>
  );
}
