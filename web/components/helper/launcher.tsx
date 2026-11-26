"use client";
import { Dialog } from "@base-ui/react/dialog";
import { Bot, Settings2, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ROUTES } from "@/components/shell/nav";
import { useT } from "@/lib/i18n";
import { useSelection } from "@/lib/selection";
import { AskPanel } from "./ask-panel";
import { useHelperOpen } from "./open-state";

/** Floating Civil Helper: a round button bottom-right on every app page, opening a chat panel.
 *  The panel stays mounted while closed, so the conversation survives closing it and moving between pages. */
export function HelperLauncher() {
  const t = useT();
  const pathname = usePathname();
  const { withSel } = useSelection();
  const { open, setOpen } = useHelperOpen();
  if (pathname.startsWith(ROUTES.job)) return null; // the crew phone job card has no assistant
  const label = t("Ask Civil Helper", "ถามผู้ช่วยวิศวกร");
  // phones: no floating button (it would sit on the content above the bottom bar); "More" opens the panel instead.
  // On the map, raised above the attribution control.
  const pos = pathname.startsWith(ROUTES.map) ? "md:bottom-14" : "md:bottom-6";
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        className={`fixed right-6 z-40 hidden size-14 md:flex items-center justify-center rounded-full bg-brand text-white shadow-lg outline-none hover:bg-brand/90 focus-visible:ring-3 focus-visible:ring-ring/50 print:hidden ${pos}`}
      >
        <Bot aria-hidden className="size-6" />
      </button>
      <Dialog.Portal keepMounted>
        <Dialog.Popup
          aria-label={t("Civil Helper", "ผู้ช่วยวิศวกร")}
          className="fixed inset-0 z-50 flex flex-col bg-popover text-sm text-popover-foreground shadow-xl outline-none transition duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0 md:inset-auto md:right-6 md:bottom-6 md:h-[560px] md:max-h-[calc(100dvh-3rem)] md:w-[380px] md:rounded-xl md:border print:hidden"
        >
          <div className="flex items-center gap-2 border-b px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))] md:pt-2">
            <Bot aria-hidden className="size-5 shrink-0 text-brand" />
            <Dialog.Title className="min-w-0 flex-1 truncate font-heading text-base font-semibold">{t("Civil Helper", "ผู้ช่วยวิศวกร")}</Dialog.Title>
            <Link
              href={withSel(ROUTES.helper)}
              onClick={() => setOpen(false)}
              className="inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-xs font-medium text-link underline underline-offset-4 md:min-h-9"
            >
              <Settings2 aria-hidden className="size-4" />
              {t("Library and settings", "คลังเอกสารและการตั้งค่า")}
            </Link>
            <Dialog.Close
              aria-label={t("Close", "ปิด")}
              className="inline-flex size-11 items-center justify-center rounded-md hover:bg-grey-50 md:size-9"
            >
              <X aria-hidden className="size-5" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            <AskPanel variant="panel" />
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
