import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NoticeBanner } from "@/components/feedback/notice-banner";
import { CheckboxGroup } from "@/components/forms/checkbox-group";
import { DailyMinutesField } from "@/components/forms/daily-minutes-field";

const OPTIONS = [
  { value: "a", label: "Alpha", hint: "The first one." },
  { value: "b", label: "Beta" },
] as const;

describe("CheckboxGroup", () => {
  it("is a named group of labelled boxes, with the chosen ones ticked", () => {
    render(<CheckboxGroup legend="Pick some" name="letters" options={OPTIONS} selected={["b"]} />);

    const group = screen.getByRole("group", { name: "Pick some" });
    expect(group).toBeInTheDocument();
    expect(screen.getByLabelText("Alpha")).not.toBeChecked();
    expect(screen.getByLabelText("Beta")).toBeChecked();
    expect(screen.getByLabelText("Beta")).toHaveAttribute("name", "letters");
    expect(screen.getByLabelText("Alpha")).toHaveAttribute("value", "a");
  });

  it("announces an option's hint with its checkbox without making it part of the label", () => {
    render(<CheckboxGroup legend="Pick some" name="letters" options={OPTIONS} selected={[]} />);

    const alpha = screen.getByLabelText("Alpha");
    expect(alpha).toHaveAccessibleDescription("The first one.");
  });

  it("ties an error to the whole group", () => {
    render(
      <CheckboxGroup
        legend="Pick some"
        name="letters"
        options={OPTIONS}
        selected={[]}
        error="Choose at least one."
      />,
    );

    expect(screen.getByRole("group", { name: "Pick some" })).toHaveAccessibleDescription(
      "Choose at least one.",
    );
    expect(screen.getByText("Choose at least one.")).toHaveAttribute("role", "alert");
  });

  it("shows the group's own hint under the legend", () => {
    render(
      <CheckboxGroup
        legend="Pick some"
        hint="Any of them."
        name="letters"
        options={OPTIONS}
        selected={[]}
      />,
    );

    expect(screen.getByRole("group", { name: "Pick some" })).toHaveAccessibleDescription(
      "Any of them.",
    );
  });
});

describe("DailyMinutesField", () => {
  it("is a required whole-number field with the allowed range shown", () => {
    render(<DailyMinutesField defaultValue="60" />);

    const input = screen.getByLabelText("Minutes you can study each day");
    expect(input).toBeRequired();
    expect(input).toHaveValue(60);
    expect(input).toHaveAttribute("min", "10");
    expect(input).toHaveAttribute("max", "480");
    expect(screen.getByText("Between 10 and 480.")).toBeInTheDocument();
  });

  it("takes its own label and shows an error", () => {
    render(<DailyMinutesField label="Usual minutes" defaultValue="5" error="Too low." />);

    const input = screen.getByLabelText("Usual minutes");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/Too low\./);
  });
});

describe("NoticeBanner", () => {
  it("shows the confirmation for a known code", () => {
    render(<NoticeBanner code="paused" />);

    expect(screen.getByText("Goal paused")).toBeInTheDocument();
    expect(screen.getByText(/Resume it whenever/)).toBeInTheDocument();
  });

  it.each([undefined, "", "nonsense", "<script>alert(1)</script>", "constructor", "__proto__"])(
    "shows nothing for the code %j, and never echoes it",
    (code) => {
      const { container } = render(<NoticeBanner code={code} />);

      expect(container).toBeEmptyDOMElement();
    },
  );

  it("warns, rather than celebrates, when something wasn't possible", () => {
    render(<NoticeBanner code="status-conflict" />);

    expect(screen.getByText(/isn't possible right now/)).toBeInTheDocument();
  });
});
