import type { ReactNode } from "react";

import { Card, CardContent, CardDescription, CardFooter, CardHeader } from "@/components/ui/card";

type AuthCardProps = {
  title: string;
  description: string;
  children: ReactNode;
  footer?: ReactNode;
};

/** The frame shared by the sign-in and sign-up screens. The title is the page's `<h1>`. */
export function AuthCard({ title, description, children, footer }: AuthCardProps) {
  return (
    <Card>
      <CardHeader>
        <h1 className="font-heading text-2xl font-semibold tracking-tight">{title}</h1>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
      {footer ? <CardFooter className="justify-center text-sm">{footer}</CardFooter> : null}
    </Card>
  );
}
