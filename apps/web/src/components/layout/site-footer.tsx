import Link from "next/link";

import { siteName } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p>{siteName} is in early development.</p>
        <nav aria-label="Footer">
          <ul className="flex gap-4">
            <li>
              <Link
                href="/status"
                className="underline-offset-4 hover:text-foreground hover:underline"
              >
                System status
              </Link>
            </li>
            <li>
              <Link
                href="/design"
                className="underline-offset-4 hover:text-foreground hover:underline"
              >
                Design system
              </Link>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
