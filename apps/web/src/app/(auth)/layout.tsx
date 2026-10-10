import type { ReactNode } from "react";

import { PageContainer } from "@/components/layout/page";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <PageContainer className="flex justify-center py-12 sm:py-20">
      <div className="w-full max-w-md">{children}</div>
    </PageContainer>
  );
}
