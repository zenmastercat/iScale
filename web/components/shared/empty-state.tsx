import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** Nothing to show yet: icon, title, one sentence, optional action (a <Button>). */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 py-12 text-center", className)}>
      {Icon && <Icon aria-hidden className="mb-3 size-8 text-grey-500" />}
      <h2 className="text-lg font-semibold text-brand">{title}</h2>
      {description && <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
