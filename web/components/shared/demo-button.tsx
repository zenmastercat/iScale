"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, PlayCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { createDemo, createSukhumvitDemo, qk } from "@/lib/api";
import { useSelection } from "@/lib/selection";
import { useT } from "@/lib/i18n";

/** Creates the demo project (POST /api/demo) and selects it. Processing then shows via SurveyGate. */
export function DemoButton({ variant = "default" }: { variant?: "default" | "outline" }) {
  return (
    <div className="flex flex-wrap justify-center gap-2">
      <DemoStreetButton variant={variant} />
      <SukhumvitButton />
    </div>
  );
}

function DemoStreetButton({ variant = "default" }: { variant?: "default" | "outline" }) {
  const qc = useQueryClient();
  const { setProject } = useSelection();
  const t = useT();
  const m = useMutation({
    mutationFn: createDemo,
    onSuccess: async (p) => {
      await qc.invalidateQueries({ queryKey: qk.projects });
      setProject(p.id);
      toast.success(t("Demo street loaded. Processing takes about 20 seconds.", "โหลดถนนตัวอย่างแล้ว ใช้เวลาประมวลผลประมาณ 20 วินาที"));
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <Button size="lg" variant={variant} className="h-11 px-4" onClick={() => m.mutate()} disabled={m.isPending}>
      {m.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <PlayCircle aria-hidden />}
      {t("Load demo street", "โหลดถนนตัวอย่าง")}
    </Button>
  );
}

/** Loads the recorded Sukhumvit Rd pothole run (17 detector findings with photos) as a ready project. */
export function SukhumvitButton({ variant = "outline" }: { variant?: "default" | "outline" }) {
  const qc = useQueryClient();
  const { setProject } = useSelection();
  const t = useT();
  const m = useMutation({
    mutationFn: createSukhumvitDemo,
    onSuccess: async (p) => {
      await qc.invalidateQueries({ queryKey: qk.projects });
      setProject(p.id);
      toast.success(t("Sukhumvit sample run loaded.", "โหลดข้อมูลจริงถนนสุขุมวิทแล้ว"));
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <Button size="lg" variant={variant} className="h-11 px-4" onClick={() => m.mutate()} disabled={m.isPending}>
      {m.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <PlayCircle aria-hidden />}
      {t("Load Sukhumvit sample run", "โหลดข้อมูลจริงถนนสุขุมวิท")}
    </Button>
  );
}
