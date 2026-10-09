import {
  BookOpenIcon,
  CircleCheckIcon,
  InfoIcon,
  InboxIcon,
  TriangleAlertIcon,
  CircleAlertIcon,
} from "lucide-react";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DialogDemo } from "@/components/design/dialog-demo";
import { EmptyState } from "@/components/feedback/empty-state";
import { CardGridSkeleton, LoadingState } from "@/components/feedback/loading-state";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { ProgressBar } from "@/components/progress/progress-bar";
import { ProgressRing } from "@/components/progress/progress-ring";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

export const metadata: Metadata = {
  title: "Design system",
  description: "Design tokens and reusable components used across the app.",
  robots: { index: false },
};

// Tailwind needs complete class names at build time, so swatches are listed explicitly.
const swatches = [
  { name: "background", className: "bg-background" },
  { name: "card", className: "bg-card" },
  { name: "muted", className: "bg-muted" },
  { name: "secondary", className: "bg-secondary" },
  { name: "accent", className: "bg-accent" },
  { name: "primary", className: "bg-primary" },
  { name: "border", className: "bg-border" },
  { name: "input", className: "bg-input" },
  { name: "ring", className: "bg-ring" },
  { name: "success", className: "bg-success" },
  { name: "warning", className: "bg-warning" },
  { name: "info", className: "bg-info" },
  { name: "destructive", className: "bg-destructive" },
] as const;

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className="space-y-5">
      <div className="space-y-1">
        <h2 id={`${id}-heading`} className="text-xl font-semibold tracking-tight">
          {title}
        </h2>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

export default function DesignSystemPage() {
  return (
    <PageContainer className="space-y-14 py-12">
      <PageHeader
        eyebrow={<Badge variant="warning">Preview · sample content</Badge>}
        title="Design system"
        description="Tokens and reusable components, shown in the current theme. Everything on this page is sample content for design review; none of it comes from a database."
      />

      <Section
        id="colour"
        title="Colour tokens"
        description="Switch theme from the header to compare light and dark."
      >
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {swatches.map((swatch) => (
            <li key={swatch.name} className="space-y-2">
              <div className={`h-14 rounded-lg border ${swatch.className}`} />
              <p className="text-xs font-medium">{swatch.name}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id="typography"
        title="Typography"
        description="Inter for the interface, Source Serif for headings and long-form reading."
      >
        <div className="space-y-4 rounded-xl border bg-card p-6">
          <p className="font-heading text-4xl font-semibold tracking-tight">
            Understand it, then prove it
          </p>
          <p className="font-heading text-2xl font-semibold tracking-tight">
            Heading two for sections
          </p>
          <p className="text-base">
            Body copy is set at 16px with comfortable line height for sustained reading. Links look
            like{" "}
            <a className="text-primary underline underline-offset-4" href="#typography">
              this
            </a>
            .
          </p>
          <p className="text-sm text-muted-foreground">
            Secondary text for supporting detail and help.
          </p>
          <p className="font-mono text-sm">kubectl get pods --namespace study</p>
          <Separator />
          <p className="text-sm text-muted-foreground">Script support (sample rendering):</p>
          <p lang="hi" className="text-lg">
            नमस्ते, सीखना शुरू करें
          </p>
          <p lang="or" className="text-lg">
            ନମସ୍କାର, ଶିଖିବା ଆରମ୍ଭ କରନ୍ତୁ
          </p>
        </div>
      </Section>

      <Section id="buttons" title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="link">Link</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm">Small</Button>
          <Button>Default</Button>
          <Button size="lg">Large</Button>
          <Button loading>Saving</Button>
          <Button disabled>Disabled</Button>
        </div>
      </Section>

      <Section
        id="forms"
        title="Form controls"
        description="Labels are always visible and programmatically linked; errors are announced."
      >
        <div className="grid gap-6 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="goal-title">Goal title</Label>
            <Input
              id="goal-title"
              placeholder="e.g. Learn Kubernetes for interviews"
              aria-describedby="goal-title-help"
            />
            <p id="goal-title-help" className="text-sm text-muted-foreground">
              Say what you want to be able to do.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="daily-minutes">Daily study time (minutes)</Label>
            <Input
              id="daily-minutes"
              inputMode="numeric"
              defaultValue="0"
              aria-invalid="true"
              aria-describedby="daily-minutes-error"
            />
            <p id="daily-minutes-error" className="text-sm text-destructive-foreground">
              Enter at least 15 minutes.
            </p>
          </div>
        </div>
      </Section>

      <Section id="cards" title="Cards">
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Container networking basics</CardTitle>
              <CardDescription>Sample roadmap item · 45 min</CardDescription>
            </CardHeader>
            <CardContent>
              <ProgressBar label="Completion" value={60} />
            </CardContent>
            <CardFooter className="justify-end">
              <Button size="sm">Continue</Button>
            </CardFooter>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Mastery</CardTitle>
              <CardDescription>Sample topic scores</CardDescription>
            </CardHeader>
            <CardContent className="flex items-center gap-6">
              <ProgressRing label="Pods mastery" value={72} />
              <ProgressRing label="Services mastery" value={38} size={72} strokeWidth={7} />
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section
        id="feedback"
        title="Alerts"
        description="Informational messages are announced politely; warnings and errors interrupt."
      >
        <div className="grid gap-3">
          <Alert variant="info">
            <InfoIcon aria-hidden="true" />
            <AlertTitle>Roadmap updated</AlertTitle>
            <AlertDescription>
              Two topics moved earlier to give you more revision time.
            </AlertDescription>
          </Alert>
          <Alert variant="success">
            <CircleCheckIcon aria-hidden="true" />
            <AlertTitle>Quiz saved</AlertTitle>
            <AlertDescription>Your answers were recorded.</AlertDescription>
          </Alert>
          <Alert variant="warning">
            <TriangleAlertIcon aria-hidden="true" />
            <AlertTitle>Daily limit almost reached</AlertTitle>
            <AlertDescription>You have one generation left today.</AlertDescription>
          </Alert>
          <Alert variant="destructive">
            <CircleAlertIcon aria-hidden="true" />
            <AlertTitle>Couldn&apos;t generate the lesson</AlertTitle>
            <AlertDescription>Nothing was charged. You can try again.</AlertDescription>
          </Alert>
        </div>
      </Section>

      <Section id="states" title="Loading and empty states">
        <LoadingState label="Generating your roadmap" className="rounded-xl border bg-card" />
        <CardGridSkeleton count={3} label="Loading goals" />
        <EmptyState
          icon={InboxIcon}
          title="No goals yet"
          description="Create your first learning goal and we'll build a roadmap around your schedule."
          action={
            <Button>
              <BookOpenIcon aria-hidden="true" />
              Create a goal
            </Button>
          }
        />
      </Section>

      <Section id="overlays" title="Dialog">
        <DialogDemo />
      </Section>
    </PageContainer>
  );
}
