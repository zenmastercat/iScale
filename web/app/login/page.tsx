"use client";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useId, useState } from "react";
import { Logo } from "@/components/shell/logo";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { setup, signIn } from "@/lib/auth";
import { qk } from "@/lib/api";
import { useAuthState } from "@/lib/queries";

const PITCH = [
  ["Video in, measured potholes out", "Depth and size are measured in 3D, not guessed."],
  ["A condition score for every 25 m", "Repair plans with costs, within your budget."],
  ["Proof the fix happened", "Drive again; each repair comes back verified, still present or not covered."],
];

function Field({
  label,
  name,
  help,
  ...rest
}: { label: string; name: string; help?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-grey-900">
        {label}
      </label>
      <input
        id={id}
        name={name}
        className="h-11 rounded-md border border-input bg-white px-3 text-base outline-none focus-visible:border-accent-blue focus-visible:ring-3 focus-visible:ring-accent-blue/30"
        aria-describedby={help ? `${id}-help` : undefined}
        {...rest}
      />
      {help && (
        <p id={`${id}-help`} className="text-sm text-muted-foreground">
          {help}
        </p>
      )}
    </div>
  );
}

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const { data: st, isLoading, refetch } = useAuthState();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const next = (() => {
    // only same-origin paths: resolve and compare origins ("/\evil.com" and "//evil.com" resolve elsewhere)
    const n = params.get("next");
    if (!n || typeof window === "undefined") return "/";
    try {
      const u = new URL(n, window.location.origin);
      if (u.origin !== window.location.origin || u.pathname.startsWith("/login")) return "/";
      return u.pathname + u.search + u.hash;
    } catch {
      return "/";
    }
  })();

  useEffect(() => {
    if (st?.user) router.replace(next);
  }, [st?.user, next, router]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      if (st?.setup_needed) await setup(String(f.get("company")), String(f.get("username")), String(f.get("display")));
      else await signIn(String(f.get("username")));
      qc.clear();
      await refetch();
      await qc.invalidateQueries({ queryKey: qk.authState });
      router.replace(next);
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh md:grid-cols-[1.1fr_1fr]">
      <section className="flex flex-col justify-center bg-sidebar px-8 py-12 text-white md:px-16" aria-labelledby="pitch">
        <Logo className="mb-10" />
        <h1 id="pitch" className="max-w-md text-3xl leading-tight font-semibold md:text-4xl">
          Find every pothole.
          <br />
          Fix the right one first.
        </h1>
        <p className="mt-4 max-w-md text-white/80">
          Road inspection for city engineering teams: survey, rank, repair and prove it, on a server your organisation runs.
        </p>
        <ul className="mt-8 hidden max-w-md flex-col gap-4 md:flex">
          {PITCH.map(([t, d]) => (
            <li key={t}>
              <p className="font-medium">{t}</p>
              <p className="text-sm text-white/75">{d}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          {isLoading || !st ? (
            <Skeleton className="h-48 w-full" />
          ) : st.setup_needed ? (
            <>
              <h2 className="text-2xl font-semibold text-brand">Set up iScale for your team</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                This server is new. You&apos;ll be its admin; engineers then sign in with just a username.
              </p>
              <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
                <Field label="Company or department" name="company" required minLength={2} maxLength={80} autoComplete="organization" placeholder="e.g. Bang Sue District Works" />
                <Field label="Your name" name="display" required maxLength={80} autoComplete="name" />
                <Field label="Your username" name="username" required maxLength={32} autoComplete="username" autoCapitalize="none" spellCheck={false} />
                <Button type="submit" size="lg" className="h-11 text-base" disabled={busy}>
                  {busy && <Loader2 className="animate-spin" aria-hidden />}Set up and sign in
                </Button>
              </form>
            </>
          ) : (
            <>
              <h2 className="text-2xl font-semibold text-brand">Sign in</h2>
              <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
                <Field
                  label="Username"
                  name="username"
                  required
                  maxLength={33}
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  autoFocus
                  placeholder="e.g. somchai.k"
                  help="No password. The first time, this device becomes yours; after that nobody can use your username from another device."
                />
                <Button type="submit" size="lg" className="h-11 text-base" disabled={busy}>
                  {busy && <Loader2 className="animate-spin" aria-hidden />}Sign in
                </Button>
              </form>
            </>
          )}
          <p role="alert" className="mt-4 min-h-5 text-sm font-medium text-sev-high-fg">
            {error}
          </p>
        </div>
      </section>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
