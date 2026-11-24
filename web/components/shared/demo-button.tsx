"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, PlayCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { createDemo, qk } from "@/lib/api";
import { useSelection } from "@/lib/selection";

/** Creates the demo project (POST /api/demo) and selects it. Processing then shows via SurveyGate. */
export function DemoButton({ variant = "default" }: { variant?: "default" | "outline" }) {
  const qc = useQueryClient();
  const { setProject } = useSelection();
  const m = useMutation({
    mutationFn: createDemo,
    onSuccess: async (p) => {
      await qc.invalidateQueries({ queryKey: qk.projects });
      setProject(p.id);
      toast.success("Demo street loaded. Processing takes about 20 seconds.");
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <Button size="lg" variant={variant} className="h-11 px-4" onClick={() => m.mutate()} disabled={m.isPending}>
      {m.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <PlayCircle aria-hidden />}
      Load demo street
    </Button>
  );
}
