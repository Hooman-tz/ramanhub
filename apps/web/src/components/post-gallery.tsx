"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  findingImageFileUrl,
  getFindingOverlay,
  getSpectrumData,
} from "@ramanhub/api-client";
import type { FindingImage } from "@ramanhub/api-client";

import { cn } from "@ramanhub/ui";
import { ScrollArea, ScrollBar } from "@ramanhub/ui/scroll-area";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { SpectrumChart } from "./charts/spectrum-chart";

type Variant = "compact" | "full";

interface Member {
  spectrum_id: string;
  label: string | null;
}

export function PostGallery({
  findingId,
  members,
  images,
  variant,
}: {
  findingId: string;
  members: Member[];
  images: FindingImage[];
  variant: Variant;
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

  const figures = images.filter((i) => i.kind === "figure");
  const abstracts = images.filter((i) => i.kind === "graphical_abstract");

  const showOverlayPanel =
    members.length > 0 && (overlay.isLoading || (overlay.data?.n ?? 0) >= 1);

  const panels: { key: string; node: React.ReactNode }[] = [];

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

  if (panels.length === 0) return null;

  const scrollToIndex = (i: number) => {
    const vp = getViewport();
    if (!vp) return;
    const clamped = Math.max(0, Math.min(i, panels.length - 1));
    vp.scrollTo({ left: clamped * vp.clientWidth, behavior: "smooth" });
  };

  const showArrows = variant === "full" && panels.length > 1;
  const showDots = panels.length > 1;

  return (
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
            className="border-border bg-background/80 hover:bg-background absolute top-1/2 left-1 flex size-8 -translate-y-1/2 items-center justify-center rounded-full border text-sm shadow-sm backdrop-blur transition-opacity disabled:opacity-30"
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="Next panel"
            onClick={() => scrollToIndex(activeIndex + 1)}
            disabled={activeIndex >= panels.length - 1}
            className="border-border bg-background/80 hover:bg-background absolute top-1/2 right-1 flex size-8 -translate-y-1/2 items-center justify-center rounded-full border text-sm shadow-sm backdrop-blur transition-opacity disabled:opacity-30"
          >
            ›
          </button>
        </>
      )}

      {showDots && (
        <div className="mt-2 flex justify-center gap-1.5">
          {panels.map((p, i) => (
            <button
              key={p.key}
              type="button"
              aria-label={`Go to panel ${i + 1}`}
              aria-current={i === activeIndex}
              onClick={() => scrollToIndex(i)}
              className={cn(
                "size-1.5 rounded-full transition-colors",
                i === activeIndex
                  ? "bg-primary"
                  : "bg-muted-foreground/30 hover:bg-muted-foreground/60",
              )}
            />
          ))}
        </div>
      )}
    </div>
  );
}

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
