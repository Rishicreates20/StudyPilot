import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NavLinks } from "@/components/layout/nav-links";

const pathname = vi.hoisted(() => ({ current: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

const items = [
  { href: "/", label: "Home" },
  { href: "/status", label: "System status" },
] as const;

describe("NavLinks", () => {
  it("marks only the current page with aria-current", () => {
    pathname.current = "/status";
    render(<NavLinks items={items} />);

    expect(screen.getByRole("link", { name: "System status" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it("treats nested routes as part of their section, but never matches Home for them", () => {
    pathname.current = "/status/history";
    render(<NavLinks items={items} />);

    expect(screen.getByRole("link", { name: "System status" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });
});
