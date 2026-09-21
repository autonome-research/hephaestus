// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The composer's image attachment (2026-09-20).
//
// Three ways in, because an operator with a screenshot will try all three: the
// button opens a file picker, a paste into the message box takes the
// clipboard's image, and a drop onto the box takes the file. All three land in
// the same list and the list is what Send carries.
//
// THE FILES ARE HELD HERE, NOT UPLOADED HERE. This component owns a list of
// `File` objects and object URLs for the thumbnails; nothing is sent until the
// turn is. That keeps a cancelled message from having left anything behind,
// and it is why `revoke` runs on every removal and on unmount — an object URL
// that outlives its thumbnail is a leak the browser cannot collect.
//
// WHAT THIS DOES NOT DO, stated because the gap is load-bearing: it does not
// yet put the images on the wire. `POST /sessions/{id}/turns` takes a text
// prompt and a context envelope; there is no image member in that contract, so
// attaching one here and sending would silently drop it. The control therefore
// collects and displays, and `onChange` hands the list up so the composer can
// refuse to send with an attachment rather than lie about carrying it.

import { useEffect, useRef } from "react";
import { copy } from "../../copy";
import { Button } from "../../system";
import styles from "./ImageAttach.module.css";

/** One held image: the file, and the object URL its thumbnail is drawn from. */
export interface HeldImage {
  readonly id: string;
  readonly file: File;
  readonly url: string;
}

let nextId = 0;

/** Wrap the files as held images, ignoring anything that is not an image. */
export function holdImages(files: readonly File[]): HeldImage[] {
  return files
    .filter((file) => file.type.startsWith("image/"))
    .map((file) => {
      nextId += 1;
      return { id: `img-${String(nextId)}`, file, url: URL.createObjectURL(file) };
    });
}

export interface ImageAttachProps {
  readonly images: readonly HeldImage[];
  readonly onChange: (images: readonly HeldImage[]) => void;
  readonly disabled?: boolean | undefined;
  readonly disabledReason?: string | undefined;
}

export function ImageAttach({
  images,
  onChange,
  disabled,
  disabledReason,
}: ImageAttachProps): React.JSX.Element {
  const input = useRef<HTMLInputElement | null>(null);
  const disablement =
    disabled === true && disabledReason !== undefined
      ? { disabled: true as const, reason: disabledReason }
      : {};
  return (
    <>
      {/* The native input is the file picker; it is never the visible control,
          because a bare `<input type="file">` cannot be styled into the row
          and its own label text is the browser's, not ours. */}
      <input
        ref={input}
        type="file"
        accept="image/*"
        multiple
        className={styles["hidden"]}
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const picked = holdImages([...(event.target.files ?? [])]);
          if (picked.length > 0) onChange([...images, ...picked]);
          // Cleared so picking the SAME file twice still fires a change.
          event.target.value = "";
        }}
      />
      <Button
        variant="toggle"
        icon="image"
        iconLabel={copy.composer.attachImage}
        pressed={images.length > 0}
        title={
          images.length > 0
            ? copy.composer.attachedImages(images.length)
            : copy.composer.attachImageWhy
        }
        onClick={() => {
          input.current?.click();
        }}
        data-composer-attach-image=""
        {...disablement}
      />
    </>
  );
}

/** The thumbnails, under the message box while anything is held. */
export function ImageStrip({
  images,
  onChange,
}: {
  readonly images: readonly HeldImage[];
  readonly onChange: (images: readonly HeldImage[]) => void;
}): React.JSX.Element | null {
  if (images.length === 0) return null;
  return (
    <ul className={styles["strip"]} data-composer-images="" aria-label={copy.composer.attachedImages(images.length)}>
      {images.map((image) => (
        <li key={image.id} className={styles["held"]}>
          <img className={styles["thumb"]} src={image.url} alt={image.file.name} />
          <Button
            variant="quiet"
            icon="close"
            iconLabel={copy.composer.removeImage(image.file.name)}
            title={copy.composer.removeImage(image.file.name)}
            onClick={() => {
              URL.revokeObjectURL(image.url);
              onChange(images.filter((held) => held.id !== image.id));
            }}
            data-composer-image-remove={image.id}
          />
        </li>
      ))}
    </ul>
  );
}

/**
 * Revoke every held URL when the composer goes away.
 *
 * The ref is written in an EFFECT, not during render: writing a ref while
 * rendering is what `react-hooks/refs` refuses, and it refuses it for a real
 * reason — a render that React throws away would still have mutated it. Two
 * effects rather than one, because the cleanup must see the LATEST list while
 * running only on unmount.
 */
export function useRevokeOnUnmount(images: readonly HeldImage[]): void {
  const held = useRef<readonly HeldImage[]>([]);
  useEffect(() => {
    held.current = images;
  }, [images]);
  useEffect(
    () => () => {
      for (const image of held.current) URL.revokeObjectURL(image.url);
    },
    [],
  );
}

/** Take images out of a paste or a drop; returns `[]` when there are none. */
export function imagesFromTransfer(data: DataTransfer | null): HeldImage[] {
  if (data === null) return [];
  return holdImages([...data.files]);
}
