/** iScale brand logo (road mark + wordmark, dark-background variant). `mark` shows the road mark only. */
export function Logo({ className, mark = false }: { className?: string; mark?: boolean }) {
  return mark ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/brand/iscale-mark.svg" alt="iScale" className={`h-6 w-auto ${className ?? ""}`} />
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/brand/iscale-logo-dark.svg" alt="iScale" className={`h-7 w-auto ${className ?? ""}`} />
  );
}
