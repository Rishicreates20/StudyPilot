import { CircleAlertIcon, CircleCheckIcon, InfoIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { noticeFor, type NoticeVariant } from "@/lib/goals/notices";

const ICONS = {
  success: CircleCheckIcon,
  info: InfoIcon,
  warning: CircleAlertIcon,
} satisfies Record<NoticeVariant, typeof InfoIcon>;

/**
 * The confirmation after an action (`?notice=paused`). Unknown codes render nothing, and no text
 * from the URL is ever shown: the code is only a key into a fixed table.
 */
export function NoticeBanner({ code }: { code: string | undefined }) {
  const notice = noticeFor(code);
  if (!notice) return null;
  const Icon = ICONS[notice.variant];

  return (
    <Alert variant={notice.variant}>
      <Icon aria-hidden="true" />
      <AlertTitle>{notice.title}</AlertTitle>
      {notice.message ? <AlertDescription>{notice.message}</AlertDescription> : null}
    </Alert>
  );
}
