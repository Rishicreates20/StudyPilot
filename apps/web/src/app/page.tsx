import {
  ArrowRightIcon,
  BookOpenIcon,
  ClipboardCheckIcon,
  CompassIcon,
  RouteIcon,
} from "lucide-react";
import Link from "next/link";

import { PageContainer } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { siteName } from "@/lib/site";

const learningLoop = [
  {
    icon: CompassIcon,
    title: "Plan",
    body: "Describe a goal, your level, your deadline and how much time you have. You get an ordered roadmap you can actually finish.",
  },
  {
    icon: BookOpenIcon,
    title: "Learn",
    body: "Each topic becomes a structured lesson with examples, key terms and a simpler explanation when you need one.",
  },
  {
    icon: ClipboardCheckIcon,
    title: "Test",
    body: "Short knowledge checks show what you understood. Answers are graded on the server and explained afterwards.",
  },
  {
    icon: RouteIcon,
    title: "Adapt",
    body: "Weak topics get more practice. Every result ends with a clear next step, not just a score.",
  },
] as const;

export default function HomePage() {
  return (
    <>
      <section className="border-b bg-gradient-to-b from-secondary/60 to-background">
        <PageContainer className="py-16 sm:py-24">
          <div className="max-w-3xl space-y-6">
            <Badge variant="info">Early development</Badge>
            <h1 className="font-heading text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              A personal coach for everything you want to learn
            </h1>
            <p className="max-w-2xl text-lg text-muted-foreground">
              {siteName} turns a goal into a plan, teaches each topic, checks what you understood
              and decides what to study next, so every session builds on the last.
            </p>
            <div className="flex flex-wrap gap-3 pt-2">
              <Button asChild size="lg" className="w-full sm:w-auto">
                <Link href="/sign-up">
                  Create your account
                  <ArrowRightIcon aria-hidden="true" />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline" className="w-full sm:w-auto">
                <Link href="/sign-in">Sign in</Link>
              </Button>
              <Button asChild size="lg" variant="ghost" className="w-full sm:w-auto">
                <Link href="#how-it-works">See how it will work</Link>
              </Button>
            </div>
          </div>
        </PageContainer>
      </section>

      <section id="how-it-works" aria-labelledby="loop-heading">
        <PageContainer className="py-16">
          <div className="max-w-2xl space-y-3">
            <h2
              id="loop-heading"
              className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl"
            >
              One loop: plan, learn, test, adapt
            </h2>
            <p className="text-muted-foreground">
              This is what is being built. Accounts and learning goals work today; AI-generated
              roadmaps, lessons and quizzes arrive in the next milestones.
            </p>
          </div>
          <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {learningLoop.map(({ icon: Icon, title, body }, index) => (
              <li key={title}>
                <Card className="h-full">
                  <CardHeader>
                    <div className="mb-2 flex items-center justify-between">
                      <div className="flex size-10 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
                        <Icon className="size-5" aria-hidden="true" />
                      </div>
                      <span className="text-sm text-muted-foreground tabular-nums">
                        Step {index + 1}
                      </span>
                    </div>
                    <CardTitle>{title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <CardDescription className="text-sm leading-relaxed">{body}</CardDescription>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ol>
        </PageContainer>
      </section>
    </>
  );
}
