import type { CSSProperties } from "react";
import type { HelperTags } from "./types";

// How much of a Tag's colour goes into its stripe; the rest is the chip's normal
// background, so the chip's ordinary text colour stays readable in light and
// dark themes alike.
const TINT_PERCENT = 55;
const CHIP_BACKGROUND = "var(--st-secondary-background-color, #eef1f5)";

function safeColour(colour: string): string {
  return /^#[0-9a-fA-F]{6}$/.test(colour) ? colour : "#888888";
}

/**
 * The Tags overlay's colouring of a chip: the chip is split into as many equal
 * vertical stripes as the person has direct Tags, one per Tag in its colour.
 * Returns no style for a person without direct Tags (the chip stays plain), and
 * a single flat tint for one Tag.
 */
export function tagStripeStyle(tags: HelperTags | null | undefined): CSSProperties | undefined {
  const direct = tags?.direct ?? [];
  if (direct.length === 0) return undefined;
  const tints = direct.map(
    (pill) => `color-mix(in srgb, ${safeColour(pill.colour)} ${TINT_PERCENT}%, ${CHIP_BACKGROUND})`,
  );
  if (tints.length === 1) return { background: tints[0] };
  const step = 100 / tints.length;
  const stops = tints.map((tint, i) => `${tint} ${(i * step).toFixed(3)}% ${((i + 1) * step).toFixed(3)}%`);
  return { background: `linear-gradient(to right, ${stops.join(", ")})` };
}

// The person's Tag names for a tooltip: direct ones, then the inherited ones.
export function tagTitle(tags: HelperTags | null | undefined): string | undefined {
  if (!tags) return undefined;
  const lines = [
    ...tags.direct.map((pill) => pill.name),
    ...tags.implied.map((pill) => `${pill.name} (zděděný)`),
  ];
  return lines.length > 0 ? `Štítky: ${lines.join(", ")}` : undefined;
}
