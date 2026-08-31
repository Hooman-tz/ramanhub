"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  deleteFindingImage,
  findingImageFileUrl,
  isApiError,
  reorderFindingImages,
  updateFindingImage,
  uploadFindingImage,
} from "@ramanhub/api-client";
import type { FindingImage } from "@ramanhub/api-client";

type Kind = FindingImage["kind"];

export function FindingImageUploader({
  findingId,
  images,
}: {
  findingId: string;
  images: FindingImage[];
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<FindingImage[]>(
    [...images].sort((a, b) => a.position - b.position),
  );
  const [kind, setKind] = useState<Kind>("figure");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["finding", findingId] });
    router.refresh();
  };

  const doUpload = async (files: FileList | null) => {
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
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const saveCaption = async (image: FindingImage, caption: string) => {
    if (caption === (image.caption ?? "")) return;
    try {
      const updated = await updateFindingImage(findingId, image.id, { caption });
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      refresh();
    } catch (e) {
      setError(isApiError(e) ? e.message : "Could not save the caption.");
    }
  };

  const remove = async (image: FindingImage) => {
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
    try {
      const finding = await reorderFindingImages(
        findingId,
        reordered.map((i) => i.id),
      );
      setItems(
        [...finding.images].sort((a, b) => a.position - b.position),
      );
      refresh();
    } catch (e) {
      setItems(items);
      setError(isApiError(e) ? e.message : "Could not reorder images.");
    }
  };

  return (
    <details className="border-border mt-6 rounded-lg border p-3">
      <summary className="cursor-pointer text-sm font-semibold">
        Figures &amp; images ({items.length})
      </summary>

      <div className="mt-3 space-y-3">
        <div className="flex items-center gap-2 text-xs">
          <label htmlFor="fig-kind" className="text-muted-foreground">
            Upload as
          </label>
          <select
            id="fig-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as Kind)}
            className="border-input bg-background rounded-md border px-2 py-1"
          >
            <option value="figure">Figure</option>
            <option value="graphical_abstract">Graphical abstract</option>
          </select>
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            void doUpload(e.dataTransfer.files);
          }}
          className={`rounded-md border border-dashed p-4 text-center text-xs transition-colors ${
            dragOver ? "border-primary bg-primary/5" : "border-border"
          }`}
        >
          <p className="text-muted-foreground">
            Drag an image here (PNG, JPEG, or WebP)
          </p>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            className="mt-2 w-full text-xs"
            disabled={busy}
            onChange={(e) => void doUpload(e.target.files)}
          />
          {busy && <p className="text-muted-foreground mt-1">Uploading…</p>}
        </div>

        {error && <p className="text-destructive text-xs">{error}</p>}

        <ul className="space-y-2">
          {items.map((image, index) => (
            <li
              key={image.id}
              className="border-border flex gap-3 rounded-md border p-2"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={findingImageFileUrl(findingId, image.id)}
                alt={image.caption ?? "Finding figure"}
                className="bg-muted size-16 shrink-0 rounded object-contain"
              />
              <div className="min-w-0 flex-1">
                <div className="text-muted-foreground text-[0.65rem] uppercase">
                  {image.kind.replace("_", " ")}
                </div>
                <input
                  defaultValue={image.caption ?? ""}
                  placeholder="Caption"
                  className="border-input bg-background mt-1 w-full rounded border px-2 py-1 text-xs"
                  onBlur={(e) => void saveCaption(image, e.target.value)}
                />
                <div className="mt-1 flex items-center gap-2 text-xs">
                  <button
                    type="button"
                    aria-label="Move up"
                    disabled={index === 0}
                    onClick={() => void move(index, -1)}
                    className="disabled:opacity-30"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    aria-label="Move down"
                    disabled={index === items.length - 1}
                    onClick={() => void move(index, 1)}
                    className="disabled:opacity-30"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(image)}
                    className="text-destructive ml-auto hover:underline"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </li>
          ))}
          {items.length === 0 && (
            <li className="text-muted-foreground text-xs">No images yet.</li>
          )}
        </ul>
      </div>
    </details>
  );
}
