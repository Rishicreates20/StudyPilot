import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

describe("Alert", () => {
  it.each(["destructive", "warning"] as const)(
    "%s alerts interrupt assistive technology",
    (variant) => {
      render(
        <Alert variant={variant}>
          <AlertTitle>Problem</AlertTitle>
          <AlertDescription>Details</AlertDescription>
        </Alert>,
      );

      expect(screen.getByRole("alert")).toHaveTextContent("Problem");
    },
  );

  it.each(["default", "info", "success"] as const)(
    "%s alerts are announced politely",
    (variant) => {
      render(
        <Alert variant={variant}>
          <AlertTitle>Note</AlertTitle>
        </Alert>,
      );

      expect(screen.getByRole("status")).toHaveTextContent("Note");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );
});
