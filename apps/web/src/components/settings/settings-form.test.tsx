import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({ saveSettingsAction: vi.fn() }));
vi.mock("@/lib/profile/actions", () => actions);

import { SettingsForm } from "@/components/settings/settings-form";
import type { SettingsValues } from "@/lib/profile/schema";

const saved: SettingsValues = {
  displayName: "Ada",
  timezone: "Asia/Kolkata",
  dailyMinutes: "45",
  languages: ["en", "hi"],
  learningPreferences: ["quizzes"],
};
const ZONES = ["Asia/Kolkata", "Europe/London", "UTC"];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SettingsForm", () => {
  it("shows what is saved", () => {
    render(<SettingsForm defaults={saved} timeZones={ZONES} />);

    expect(screen.getByLabelText(/Your name/)).toHaveValue("Ada");
    expect(screen.getByLabelText("Your timezone")).toHaveValue("Asia/Kolkata");
    expect(screen.getByLabelText("Usual minutes of study per day")).toHaveValue(45);
    expect(screen.getByLabelText("English")).toBeChecked();
    expect(screen.getByLabelText(/Hindi/)).toBeChecked();
    expect(screen.getByLabelText(/Odia/)).not.toBeChecked();
    expect(screen.getByLabelText("Practice quizzes")).toBeChecked();
    expect(screen.getByLabelText("Worked examples")).not.toBeChecked();
  });

  it("keeps a saved timezone selectable even if the list doesn't name it", () => {
    render(<SettingsForm defaults={{ ...saved, timezone: "Asia/Calcutta" }} timeZones={ZONES} />);

    expect(screen.getByLabelText("Your timezone")).toHaveValue("Asia/Calcutta");
  });

  it("sends everything that was changed", async () => {
    actions.saveSettingsAction.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    render(<SettingsForm defaults={saved} timeZones={ZONES} />);

    await user.clear(screen.getByLabelText(/Your name/));
    await user.type(screen.getByLabelText(/Your name/), "Ada Lovelace");
    await user.selectOptions(screen.getByLabelText("Your timezone"), "Europe/London");
    await user.click(screen.getByLabelText("Spaced revision"));
    await user.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => expect(actions.saveSettingsAction).toHaveBeenCalledTimes(1));
    const data = actions.saveSettingsAction.mock.calls[0]?.[1] as FormData;
    expect(data.get("displayName")).toBe("Ada Lovelace");
    expect(data.get("timezone")).toBe("Europe/London");
    expect(data.get("dailyMinutes")).toBe("45");
    expect(data.getAll("languages")).toEqual(["en", "hi"]);
    expect(data.getAll("learningPreferences")).toEqual(["quizzes", "revision"]);
  });

  it("confirms the save and shows the saved values, not the old ones", async () => {
    actions.saveSettingsAction.mockResolvedValue({
      status: "success",
      message: "Your preferences are saved.",
      values: { ...saved, displayName: "Ada Lovelace", dailyMinutes: "90" },
    });
    const user = userEvent.setup();
    render(<SettingsForm defaults={saved} timeZones={ZONES} />);

    const minutes = screen.getByLabelText("Usual minutes of study per day");
    await user.clear(minutes);
    await user.type(minutes, "90");
    await user.click(screen.getByRole("button", { name: "Save preferences" }));

    expect(await screen.findByText("Your preferences are saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Usual minutes of study per day")).toHaveValue(90);
    expect(screen.getByLabelText(/Your name/)).toHaveValue("Ada Lovelace");
  });

  it("explains a failure next to the field and keeps the answers", async () => {
    actions.saveSettingsAction.mockResolvedValue({
      status: "error",
      fieldErrors: { timezone: "Choose a timezone from the list, for example Asia/Kolkata." },
      values: { ...saved, dailyMinutes: "120" },
    });
    const user = userEvent.setup();
    render(<SettingsForm defaults={saved} timeZones={ZONES} />);

    await user.click(screen.getByRole("button", { name: "Save preferences" }));

    expect(await screen.findByText(/Choose a timezone from the list/)).toBeInTheDocument();
    expect(screen.getByLabelText("Your timezone")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Usual minutes of study per day")).toHaveValue(120);
  });

  it("says that existing goals keep their own settings", () => {
    render(<SettingsForm defaults={saved} timeZones={ZONES} />);

    expect(screen.getByText(/already created keep their own settings/)).toBeInTheDocument();
  });
});
