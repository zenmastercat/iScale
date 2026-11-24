"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { createDemo, qk } from "@/lib/api";
import { useMeta } from "@/lib/queries";
import { useSelection } from "@/lib/selection";
import { cn } from "@/lib/utils";
import { uploadSurvey } from "./upload";

type Source = "video" | "lidar" | "demo";
const SOURCES: { key: Source; label: string; decoder: string; hint: string; accept: string }[] = [
  { key: "video", label: "Drive video", decoder: "pothole_video", hint: "A dash-cam video, plus an optional gps.csv.", accept: "video/*,.csv" },
  { key: "lidar", label: "LiDAR point cloud", decoder: "ply_import", hint: "A PLY file and its poses, plus an optional gps.csv.", accept: ".ply,.csv,.txt,.json" },
  { key: "demo", label: "Demo street", decoder: "", hint: "Adds the synthetic demo project (before and after repairs).", accept: "" },
];

const inputCls = "h-11 w-full rounded-lg border bg-card px-3 text-base";

export function AddSurveyDialog() {
  const { projectId, setProject } = useSelection();
  const { data: meta } = useMeta();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<Source>("video");
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [height, setHeight] = useState("");
  const [progress, setProgress] = useState<number | null>(null);

  const src = SOURCES.find((s) => s.key === source)!;
  const dec = meta?.decoders.find((d) => d.name === src.decoder);
  const unavailable = source !== "demo" && !!dec && !dec.available;

  const submit = useMutation({
    mutationFn: async () => {
      if (source === "demo") return { demo: await createDemo() };
      const params: Record<string, unknown> =
        source === "lidar" ? { metric: true, up_axis: "z" } : height ? { camera_height_m: +height } : {};
      const fd = new FormData();
      fd.append("name", name.trim());
      fd.append("decoder", src.decoder);
      fd.append("params", JSON.stringify(params));
      for (const f of files) fd.append("files", f, f.name);
      return { survey: await uploadSurvey(projectId!, fd, setProgress) };
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: qk.projects });
      if (r.demo) {
        setProject(r.demo.id);
        toast.success("Demo street added. Processing takes about 20 seconds.");
      } else {
        qc.invalidateQueries({ queryKey: qk.project(projectId!) });
        toast.success(`Uploaded ${r.survey!.name}. Processing has started.`);
      }
      setOpen(false);
      setName("");
      setFiles([]);
      setHeight("");
    },
    onError: (e: Error) => toast.error(e.message),
    onSettled: () => setProgress(null),
  });

  const needsFiles = source !== "demo";
  const valid = source === "demo" || (!!projectId && name.trim() && files.length > 0 && !unavailable);

  return (
    <Dialog open={open} onOpenChange={(o) => !submit.isPending && setOpen(o)}>
      <DialogTrigger render={<Button className="min-h-11" />}>
        <Plus aria-hidden /> Add survey
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add survey</DialogTitle>
          <DialogDescription>Choose where the drive data comes from.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) submit.mutate();
          }}
        >
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium text-grey-700">Source</legend>
            {SOURCES.map((s) => {
              const d = meta?.decoders.find((x) => x.name === s.decoder);
              const off = s.key !== "demo" && !!d && !d.available;
              return (
                <label
                  key={s.key}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border p-3",
                    source === s.key && "border-brand bg-brand-50",
                    off && "cursor-not-allowed opacity-70",
                  )}
                >
                  <input
                    type="radio"
                    name="source"
                    className="mt-1 size-4"
                    checked={source === s.key}
                    disabled={off}
                    onChange={() => setSource(s.key)}
                  />
                  <span>
                    <span className="block font-medium">{s.label}</span>
                    <span className="block text-sm text-muted-foreground">{s.hint}</span>
                    {off && <span className="block text-sm text-sev-high-fg">Not available: {d?.unavailable_reason}</span>}
                  </span>
                </label>
              );
            })}
          </fieldset>

          {needsFiles && (
            <>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="survey-name" className="text-sm font-medium text-grey-700">Survey name</label>
                <input id="survey-name" className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="survey-files" className="text-sm font-medium text-grey-700">
                  {source === "video" ? "Video and optional gps.csv" : "PLY, poses and optional gps.csv"}
                </label>
                <input
                  id="survey-files"
                  type="file"
                  multiple
                  accept={src.accept}
                  className="min-h-11 w-full rounded-lg border bg-card p-2 text-sm"
                  onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                />
              </div>
              {source === "video" && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="survey-height" className="text-sm font-medium text-grey-700">Camera height in metres (optional)</label>
                  <input id="survey-height" type="number" step="0.01" min="0.3" max="4" inputMode="decimal" className={`${inputCls} num`} value={height} onChange={(e) => setHeight(e.target.value)} />
                </div>
              )}
            </>
          )}

          {progress !== null && (
            <div>
              <div role="progressbar" aria-label="Upload progress" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100} className="h-2 w-full overflow-hidden rounded-full bg-grey-100">
                <div className="h-full bg-brand transition-[width]" style={{ width: `${progress * 100}%` }} />
              </div>
              <p className="num mt-1 text-sm text-muted-foreground">Uploading {Math.round(progress * 100)}%</p>
            </div>
          )}
          <Button type="submit" className="min-h-11" disabled={!valid || submit.isPending}>
            {submit.isPending ? "Working…" : source === "demo" ? "Add demo street" : "Upload and process"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
