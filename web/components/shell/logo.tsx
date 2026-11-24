/** iScale mark: a short condition strip with two chainage ticks. */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 text-xl font-semibold text-white ${className ?? ""}`}>
      <svg viewBox="0 0 28 20" width="28" height="20" aria-hidden="true">
        <rect x="0" y="8" width="7" height="4" fill="#3fb37f" />
        <rect x="7" y="8" width="7" height="4" fill="#e8c547" />
        <rect x="14" y="8" width="7" height="4" fill="#ef8f36" />
        <rect x="21" y="8" width="7" height="4" fill="#3fb37f" />
        <path d="M10 4v12M24 4v12" stroke="currentColor" strokeWidth="1.6" />
      </svg>
      iScale
    </span>
  );
}
