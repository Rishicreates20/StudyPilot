import Link from "next/link";

import { PageContainer, PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { DASHBOARD_PATH } from "@/lib/auth/paths";

/**
 * Shown for a missing page and for a goal that doesn't exist or isn't yours: the two look
 * identical on purpose, so nobody can probe which goals exist.
 */
export default function AppNotFound() {
  return (
    <PageContainer className="max-w-2xl py-16">
      <PageHeader
        title="We couldn't find that"
        description="It may have been deleted, or it may belong to a different account."
        actions={
          <Button asChild size="lg">
            <Link href={DASHBOARD_PATH}>Back to your goals</Link>
          </Button>
        }
      />
    </PageContainer>
  );
}
