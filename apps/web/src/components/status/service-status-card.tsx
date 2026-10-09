import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export type ServiceState = "operational" | "degraded" | "unreachable";

const stateBadge: Record<ServiceState, { variant: BadgeVariant; label: string }> = {
  operational: { variant: "success", label: "Operational" },
  degraded: { variant: "warning", label: "Degraded" },
  unreachable: { variant: "destructive", label: "Unreachable" },
};

type ServiceStatusCardProps = {
  name: string;
  description: string;
  state: ServiceState;
  icon: LucideIcon;
  /** Short facts such as version or latency. */
  details?: readonly { label: string; value: ReactNode }[];
  children?: ReactNode;
};

export function ServiceStatusCard({
  name,
  description,
  state,
  icon: Icon,
  details,
  children,
}: ServiceStatusCardProps) {
  const badge = stateBadge[state];
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
              <Icon className="size-5" aria-hidden="true" />
            </div>
            <div>
              <CardTitle>{name}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </div>
          </div>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
      </CardHeader>
      {details?.length || children ? (
        <CardContent className="space-y-4">
          {details?.length ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              {details.map(({ label, value }) => (
                <div key={label} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="font-medium tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {children}
        </CardContent>
      ) : null}
    </Card>
  );
}
