import { CompassIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/feedback/empty-state";
import { PageContainer } from "@/components/layout/page";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <PageContainer className="py-16">
      <EmptyState
        headingLevel="h2"
        icon={CompassIcon}
        title="We can't find that page"
        description="The link may be out of date, or the page may have moved."
        action={
          <Button asChild>
            <Link href="/">Back to home</Link>
          </Button>
        }
      />
    </PageContainer>
  );
}
