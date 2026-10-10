import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({ signInAction: vi.fn(), signUpAction: vi.fn() }));
vi.mock("@/lib/auth/actions", () => actions);

import { SignInForm } from "@/components/auth/sign-in-form";
import { SignUpForm } from "@/components/auth/sign-up-form";

const submittedForm = (mock: typeof actions.signInAction): FormData =>
  mock.mock.calls[0]?.[1] as FormData;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SignInForm", () => {
  it("labels its fields, masks the password and carries the return-to page", () => {
    const { container } = render(<SignInForm next="/goals/new" />);

    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Email")).toHaveAttribute("autocomplete", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
    expect(container.querySelector('input[name="next"]')).toHaveValue("/goals/new");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("sends what was typed to the server action", async () => {
    actions.signInAction.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    render(<SignInForm next="/dashboard" />);

    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(actions.signInAction).toHaveBeenCalledTimes(1));
    const data = submittedForm(actions.signInAction);
    expect(data.get("email")).toBe("ada@example.com");
    expect(data.get("password")).toBe("correct horse battery");
    expect(data.get("next")).toBe("/dashboard");
  });

  it("shows the failure, keeps the email and never puts the password back", async () => {
    actions.signInAction.mockResolvedValue({
      status: "error",
      formError: "The email or password is incorrect.",
      fieldErrors: {},
      values: { email: "ada@example.com" },
    });
    const user = userEvent.setup();
    render(<SignInForm next="/dashboard" />);

    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong password here");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("The email or password is incorrect.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue("ada@example.com");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("ties a field error to its input for assistive technology", async () => {
    actions.signInAction.mockResolvedValue({
      status: "error",
      // The browser already blocks a malformed address, so this is the server being stricter.
      fieldErrors: { email: "Enter a valid email address." },
      values: { email: "ada@example" },
    });
    const user = userEvent.setup();
    render(<SignInForm next="/dashboard" />);

    await user.type(screen.getByLabelText("Email"), "ada@example");
    await user.type(screen.getByLabelText("Password"), "whatever");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const message = await screen.findByText("Enter a valid email address.");
    const email = screen.getByLabelText("Email");
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email.getAttribute("aria-describedby")).toContain(message.id);
  });
});

describe("SignUpForm", () => {
  it("asks for an optional name, an email and a password with the length rule visible", () => {
    render(<SignUpForm />);

    expect(screen.getByLabelText(/Your name/)).not.toBeRequired();
    expect(screen.getByLabelText("Email")).toBeRequired();
    const password = screen.getByLabelText("Password");
    expect(password).toBeRequired();
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "new-password");
    expect(password).toHaveAttribute("minlength", "10");
    expect(screen.getByText(/Use 10 or more characters/)).toBeInTheDocument();
  });

  it("sends the details to the server action", async () => {
    actions.signUpAction.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    render(<SignUpForm />);

    await user.type(screen.getByLabelText(/Your name/), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(actions.signUpAction).toHaveBeenCalledTimes(1));
    const data = submittedForm(actions.signUpAction);
    expect(data.get("displayName")).toBe("Ada");
    expect(data.get("email")).toBe("ada@example.com");
    expect(data.get("password")).toBe("correct horse battery");
  });

  it("asks the user to check their email when confirmation is required", async () => {
    actions.signUpAction.mockResolvedValue({ status: "check-email", email: "ada@example.com" });
    const user = userEvent.setup();
    render(<SignUpForm />);

    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Check your email")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
    // The form (and with it the password field) is gone.
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("keeps the name and email after a failure, but not the password", async () => {
    actions.signUpAction.mockResolvedValue({
      status: "error",
      formError: "That password is too easy to guess. Try a few random words.",
      fieldErrors: {},
      values: { displayName: "Ada", email: "ada@example.com" },
    });
    const user = userEvent.setup();
    render(<SignUpForm />);

    await user.type(screen.getByLabelText(/Your name/), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "password1234");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText(/too easy to guess/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Your name/)).toHaveValue("Ada");
    expect(screen.getByLabelText("Email")).toHaveValue("ada@example.com");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});
