import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { percentOf, ProgressBar } from "@/components/progress/progress-bar";
import { ProgressRing } from "@/components/progress/progress-ring";

describe("percentOf", () => {
  it.each([
    [0, 100, 0],
    [50, 100, 50],
    [1, 3, 33],
    [150, 100, 100], // clamped
    [-5, 100, 0], // clamped
    [5, 0, 0], // no division by zero
    [Number.NaN, 100, 0],
  ])("percentOf(%s, %s) is %s", (value, max, expected) => {
    expect(percentOf(value, max)).toBe(expected);
  });
});

describe("ProgressBar", () => {
  it("exposes its label and value to assistive technology", () => {
    render(<ProgressBar label="Roadmap completion" value={3} max={4} />);

    const bar = screen.getByRole("progressbar", { name: "Roadmap completion" });
    expect(bar).toHaveAttribute("aria-valuenow", "75");
    expect(bar).toHaveAttribute("aria-valuetext", "75%");
    expect(screen.getByText("75%")).toBeInTheDocument();
  });

  it("can hide the visible percentage without hiding the value from assistive technology", () => {
    render(<ProgressBar label="Mastery" value={40} showValue={false} />);

    expect(screen.queryByText("40%")).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Mastery" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
  });
});

describe("ProgressRing", () => {
  it("is a named progressbar with a clamped value", () => {
    render(<ProgressRing label="Pods mastery" value={130} />);

    const ring = screen.getByRole("progressbar", { name: "Pods mastery" });
    expect(ring).toHaveAttribute("aria-valuenow", "100");
    expect(ring).toHaveAttribute("aria-valuemin", "0");
    expect(ring).toHaveAttribute("aria-valuemax", "100");
  });
});
