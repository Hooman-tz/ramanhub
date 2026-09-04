"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  ImagePlus,
  Trash2,
} from "lucide-react";

import type { FindingImage } from "@ramanhub/api-client";
import {
  deleteFindingImage,
  findingImageFileUrl,
  getFindingOverlay,
  getSpectrumData,
  isApiError,
  reorderFindingImages,
  updateFindingImage,
  uploadFindingImage,
} from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Input } from "@ramanhub/ui/input";
import { ScrollArea, ScrollBar } from "@ramanhub/ui/scroll-area";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { SpectrumChart } from "./charts/spectrum-chart";
import { SpectrumExplorer } from "./charts/spectrum-explorer";

type Variant = "compact" | "full";
type Kind = FindingImage["kind"];

interface Member {
  spectrum_id: string;
  label: string | null;
}

interface Panel {
  key: string;
  node: React.ReactNode;
  /** Set on image panels so the owner toolbar knows what it is editing. */
  image?: FindingImage;
  /** True for the trailing "add a figure" tile. */
  isAdder?: boolean;
}

export function PostGallery({
  findingId,
  members,
  images,
  variant,
  isOwner = false,
  title,
}: {
  findingId: string;
  members: Member[];
  images: FindingImage[];
  variant: Variant;
  /**
   * Show the inline figure controls. Editing lives on the figure itself
   * rather than in a separate collapsible below the post — the panel you are
   * looking at is the one you edit.
   */
  isOwner?: boolean;
  /** Used as the explorer dialog's heading. */
  title?: string;
}) {
  const chartHeight = variant === "compact" ? 200 : 340;
  const rootRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const overlay = useQuery({
    queryKey: ["overlay", findingId],
    queryFn: () => getFindingOverlay(findingId),
    enabled: members.length > 0,
  });

  const getViewport = () =>
    rootRef.current?.querySelector<HTMLElement>(
      "[data-slot=scroll-area-viewport]",
    ) ?? null;

  // Owner edits mutate this list optimistically; readers just render `images`.
  const [items, setItems] = useState<FindingImage[]>(() =>
    [...images].sort((a, b) => a.position - b.position),
  );
  // Re-sync when the parent hands down a new list. Adjusting state during
  // render is React's documented pattern for this and avoids the cascading
  // second render an effect would cause; `items` is never briefly stale.
  const [syncedImages, setSyncedImages] = useState(images);
  if (syncedImages !== images) {
    setSyncedImages(images);
    setItems([...images].sort((a, b) => a.position - b.position));
  }

  const figures = items.filter((i) => i.kind === "figure");
  const abstracts = items.filter((i) => i.kind === "graphical_abstract");

  const showOverlayPanel =
    members.length > 0 && (overlay.isLoading || (overlay.data?.n ?? 0) >= 1);

  const panels: Panel[] = [];

  if (showOverlayPanel) {
    panels.push({
      key: "overlay",
      node:
        overlay.data && overlay.data.n >= 1 ? (
          <SpectrumChart
            mode="band"
            grid={overlay.data.grid_wavenumbers}
            mean={overlay.data.mean}
            std={overlay.data.std}
            height={chartHeight}
            ariaLabel={`Mean of ${overlay.data.n} member spectra with a ±1 SD band`}
          />
        ) : (
          <Skeleton style={{ height: chartHeight }} className="w-full" />
        ),
    });
  }

  for (const m of members) {
    panels.push({
      key: `spec-${m.spectrum_id}`,
      node: (
        <MemberTracePanel
          spectrumId={m.spectrum_id}
          label={m.label}
          height={chartHeight}
        />
      ),
    });
  }

  for (const img of [...figures, ...abstracts]) {
    panels.push({
      key: `img-${img.id}`,
      image: img,
      node: (
        <ImagePanel
          findingId={findingId}
          image={img}
          height={chartHeight}
          showCaption={variant === "full"}
        />
      ),
    });
  }

  const showEditing = isOwner && variant === "full";

  const explorerSpectra = useMemo(
    () => members.map((m) => ({ spectrum_id: m.spectrum_id, label: m.label })),
    [members],
  );

  useEffect(() => {
    const vp = getViewport();
    if (!vp) return;
    const onScroll = () => {
      const w = Math.max(1, vp.clientWidth);
      setActiveIndex(Math.round(vp.scrollLeft / w));
    };
    vp.addEventListener("scroll", onScroll, { passive: true });
    return () => vp.removeEventListener("scroll", onScroll);
  }, [panels.length]);

  const scrollToIndex = (i: number) => {
    const vp = getViewport();
    if (!vp) return;
    const clamped = Math.max(0, Math.min(i, panels.length - 1));
    vp.scrollTo({ left: clamped * vp.clientWidth, behavior: "smooth" });
  };

  const editor = useFigureEditing(findingId, items, setItems);

  if (showEditing) {
    panels.push({
      key: "add-figure",
      isAdder: true,
      node: <AddFigurePanel height={chartHeight} editor={editor} />,
    });
  }

  if (panels.length === 0) return null;

  const showArrows = variant === "full" && panels.length > 1;
  const showDots = panels.length > 1;
  const activePanel = panels[activeIndex];
  const activeImage = activePanel?.image;
  // Index within `items`, which the reorder buttons need — not the panel index,
  // which also counts chart panels.
  const activeImageIndex = activeImage
    ? items.findIndex((i) => i.id === activeImage.id)
    : -1;

  return (
    <div className="space-y-2">
      {variant === "full" && members.length > 0 && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground text-xs">
            {panels.length} {panels.length === 1 ? "panel" : "panels"}
          </span>
          <SpectrumExplorer
            spectra={explorerSpectra}
            title={title ?? "Explore the data"}
          />
        </div>
      )}

      <div ref={rootRef} className="relative">
        <ScrollArea className="w-full">
          <div className="flex snap-x snap-mandatory">
            {panels.map((p) => (
              <div key={p.key} className="w-full shrink-0 snap-center">
                {p.node}
              </div>
            ))}
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>

        {showArrows && (
          <>
            <button
              type="button"
              aria-label="Previous panel"
              onClick={() => scrollToIndex(activeIndex - 1)}
              disabled={activeIndex <= 0}
              className="border-border bg-background/80 hover:bg-background focus-visible:ring-ring/50 absolute top-1/2 left-1 flex size-9 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full border shadow-sm backdrop-blur transition-colors focus-visible:ring-[3px] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-30 motion-reduce:transition-none"
            >
              <ChevronLeft className="size-5" aria-hidden />
            </button>
            <button
              type="button"
              aria-label="Next panel"
              onClick={() => scrollToIndex(activeIndex + 1)}
              disabled={activeIndex >= panels.length - 1}
              className="border-border bg-background/80 hover:bg-background focus-visible:ring-ring/50 absolute top-1/2 right-1 flex size-9 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full border shadow-sm backdrop-blur transition-colors focus-visible:ring-[3px] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-30 motion-reduce:transition-none"
            >
              <ChevronRight className="size-5" aria-hidden />
            </button>
          </>
        )}

        {showDots && (
          <div className="mt-2 flex justify-center gap-1">
            {panels.map((p, i) => (
              <button
                key={p.key}
                type="button"
                aria-label={
                  p.isAdder
                    ? "Go to the add-a-figure panel"
                    : `Go to panel ${i + 1} of ${panels.length}`
                }
                aria-current={i === activeIndex}
                onClick={() => scrollToIndex(i)}
                className="focus-visible:ring-ring/50 group flex size-8 cursor-pointer items-center justify-center rounded-full focus-visible:ring-[3px] focus-visible:outline-none"
              >
                <span
                  className={cn(
                    "size-2 rounded-full transition-colors motion-reduce:transition-none",
                    i === activeIndex
                      ? "bg-primary"
                      : p.isAdder
                        ? "border-foreground/40 size-2.5 border border-dashed"
                        : "bg-foreground/25 group-hover:bg-foreground/50",
                  )}
                />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* The owner toolbar for whichever figure is on screen. Replaces the old
          "Figures & images" collapsible: the figures are already rendered
          here, so the controls belong here too rather than in a second list
          further down the page. */}
      {showEditing && activeImage && activeImageIndex >= 0 && (
        <FigureToolbar
          key={activeImage.id}
          image={activeImage}
          index={activeImageIndex}
          total={items.length}
          editor={editor}
        />
      )}

      {showEditing && editor.error && (
        <p className="text-destructive text-xs">{editor.error}</p>
      )}
    </div>
  );
}

/* --- owner editing ------------------------------------------------- */

type FigureEditor = ReturnType<typeof useFigureEditing>;

function useFigureEditing(
  findingId: string,
  items: FindingImage[],
  setItems: React.Dispatch<React.SetStateAction<FindingImage[]>>,
) {
  const router = useRouter();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["finding", findingId] });
    router.refresh();
  };

  const upload = async (files: FileList | null, kind: Kind) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        const created = await uploadFindingImage(findingId, { file, kind });
        setItems((prev) =>
          prev.some((i) => i.id === created.id) ? prev : [...prev, created],
        );
      }
      refresh();
    } catch (e) {
      setError(
        isApiError(e) ? e.message : "Upload failed — check the file type/size.",
      );
    } finally {
      setBusy(false);
    }
  };

  const saveCaption = async (image: FindingImage, caption: string) => {
    if (caption === (image.caption ?? "")) return;
    setError(null);
    try {
      const updated = await updateFindingImage(findingId, image.id, {
        caption,
      });
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      refresh();
    } catch (e) {
      setError(isApiError(e) ? e.message : "Could not save the caption.");
    }
  };

  const remove = async (image: FindingImage) => {
    setError(null);
    try {
      await deleteFindingImage(findingId, image.id);
      setItems((prev) => prev.filter((i) => i.id !== image.id));
      refresh();
    } catch (e) {
      setError(isApiError(e) ? e.message : "Could not delete the image.");
    }
  };

  const move = async (index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= items.length) return;
    const row = items[index];
    if (!row) return;
    const reordered = items.filter((_, i) => i !== index);
    reordered.splice(next, 0, row);
    setItems(reordered);
    setError(null);
    try {
      const finding = await reorderFindingImages(
        findingId,
        reordered.map((i) => i.id),
      );
      setItems([...finding.images].sort((a, b) => a.position - b.position));
      refresh();
    } catch (e) {
      setItems(items);
      setError(isApiError(e) ? e.message : "Could not reorder images.");
    }
  };

  return { busy, error, upload, saveCaption, remove, move };
}

function AddFigurePanel({
  height,
  editor,
}: {
  height: number;
  editor: FigureEditor;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<Kind>("figure");
  const [dragOver, setDragOver] = useState(false);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        void editor.upload(e.dataTransfer.files, kind);
        if (fileRef.current) fileRef.current.value = "";
      }}
      style={{ height }}
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-md border border-dashed p-4 text-center transition-colors motion-reduce:transition-none",
        dragOver ? "border-primary bg-primary/5" : "border-border",
      )}
    >
      <ImagePlus className="text-muted-foreground size-6" aria-hidden />
      <p className="text-muted-foreground text-xs">
        Drag an image here, or choose a file (PNG, JPEG, WebP)
      </p>

      <div className="flex flex-wrap items-center justify-center gap-2 text-xs">
        <label htmlFor="fig-kind" className="text-foreground/80">
          Add as
        </label>
        <select
          id="fig-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
          className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring h-9 cursor-pointer rounded-md border px-2 focus-visible:ring-[3px] focus-visible:outline-none"
        >
          <option value="figure">Figure</option>
          <option value="graphical_abstract">Graphical abstract</option>
        </select>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        aria-label="Choose figure files to upload"
        className="max-w-full text-xs"
        disabled={editor.busy}
        onChange={(e) => {
          void editor.upload(e.target.files, kind);
          e.target.value = "";
        }}
      />
      {editor.busy && (
        <p className="text-muted-foreground text-xs">Uploading…</p>
      )}
    </div>
  );
}

function FigureToolbar({
  image,
  index,
  total,
  editor,
}: {
  image: FindingImage;
  index: number;
  total: number;
  editor: FigureEditor;
}) {
  const btn =
    "flex size-11 cursor-pointer items-center justify-center rounded-md transition-colors focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-30 motion-reduce:transition-none";

  return (
    <div className="border-border bg-card flex flex-wrap items-center gap-2 rounded-lg border p-2">
      <span className="text-muted-foreground shrink-0 text-[0.65rem] uppercase">
        {image.kind.replace("_", " ")}
      </span>
      <Input
        key={image.id}
        defaultValue={image.caption ?? ""}
        placeholder="Add a caption"
        aria-label="Figure caption"
        className="h-11 min-w-40 flex-1 text-xs"
        onBlur={(e) => void editor.saveCaption(image, e.target.value)}
      />
      <button
        type="button"
        aria-label="Move this figure earlier"
        disabled={index === 0}
        onClick={() => void editor.move(index, -1)}
        className={cn(btn, "hover:bg-muted")}
      >
        <ArrowUp className="size-4" aria-hidden />
      </button>
      <button
        type="button"
        aria-label="Move this figure later"
        disabled={index === total - 1}
        onClick={() => void editor.move(index, 1)}
        className={cn(btn, "hover:bg-muted")}
      >
        <ArrowDown className="size-4" aria-hidden />
      </button>
      <button
        type="button"
        aria-label="Delete this figure"
        onClick={() => void editor.remove(image)}
        className={cn(btn, "text-destructive hover:bg-destructive/10")}
      >
        <Trash2 className="size-4" aria-hidden />
      </button>
    </div>
  );
}

/* --- panels --------------------------------------------------------- */

function MemberTracePanel({
  spectrumId,
  label,
  height,
}: {
  spectrumId: string;
  label: string | null;
  height: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (visible) return;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "250px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  const q = useQuery({
    queryKey: ["spectrum-data", spectrumId],
    queryFn: () => getSpectrumData(spectrumId),
    enabled: visible,
  });

  return (
    <div ref={ref}>
      {label && (
        <div className="text-muted-foreground mb-1 truncate px-1 text-xs">
          {label}
        </div>
      )}
      {q.data ? (
        <SpectrumChart
          mode="trace"
          wavenumbers={q.data.wavenumbers}
          intensities={q.data.intensities}
          height={height}
          ariaLabel={`Spectrum ${label ?? spectrumId}`}
        />
      ) : q.isError ? (
        <div
          className="text-muted-foreground flex items-center justify-center text-xs"
          style={{ height }}
        >
          Could not load this spectrum.
        </div>
      ) : (
        <Skeleton style={{ height }} className="w-full" />
      )}
    </div>
  );
}

function ImagePanel({
  findingId,
  image,
  height,
  showCaption,
}: {
  findingId: string;
  image: FindingImage;
  height: number;
  showCaption: boolean;
}) {
  return (
    <figure className="flex flex-col">
      <div
        className="bg-muted flex items-center justify-center overflow-hidden rounded-md"
        style={{ height }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={findingImageFileUrl(findingId, image.id)}
          alt={image.caption ?? "Finding figure"}
          className="max-h-full max-w-full object-contain"
        />
      </div>
      {showCaption && image.caption && (
        <figcaption className="text-muted-foreground mt-1 px-1 text-xs">
          {image.caption}
        </figcaption>
      )}
    </figure>
  );
}
