import { useDraggable } from "@dnd-kit/core";
import type { CSSProperties } from "react";
import type { HelperTags, OrganizerSource } from "./types";
import { tagStripeStyle, tagTitle } from "./tagStripes";

interface Props {
  organizerId: number;
  name: string;
  // The slot cell the chip sits in, null for a chip in the Nezařazení list.
  source: OrganizerSource | null;
  showTags?: boolean;
  tags?: HelperTags | null;
  dimmed?: boolean;
  broken?: string[];
  // Given for a chip in a slot cell: its "×" button takes the Organizer out.
  onRemove?: () => void;
}

/**
 * A tracked Organizer's chip, draggable like a Helper's (see HelperChip) but only
 * onto the Organizer rows' slot cells — the drag carries `kind: "organizer"`,
 * which the solver-role and Additional-role cells refuse. Dragged out of a slot
 * cell it moves the Organizer, from the Nezařazení list it places them.
 */
export function OrganizerChip({ organizerId, name, source, showTags = false, tags, dimmed, broken, onRemove }: Props) {
  const sourceKey = source ? `${source.key}::${source.building}::${source.room ?? ""}` : "pool";
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `org:${organizerId}:${sourceKey}`,
    data: { kind: "organizer", organizerId, source },
  });

  const stripes = showTags ? tagStripeStyle(tags) : undefined;
  const style: CSSProperties = {
    ...stripes,
    ...(transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 } : undefined),
  };
  const title = [...(broken ?? []), ...(showTags ? [tagTitle(tags) ?? ""] : [])].filter(Boolean).join("\n") || undefined;

  return (
    <span
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      title={title}
      // A click on a chip is not a click on the cell, which opens its name field.
      onClick={(e) => e.stopPropagation()}
      className={`manual-chip organizer-chip${stripes ? " tag-striped" : ""}${dimmed ? " dimmed" : ""}${broken?.length ? " broken" : ""}${isDragging ? " dragging" : ""}`}
    >
      {name}
      {onRemove && (
        <button
          type="button"
          className="manual-chip-remove"
          aria-label={`Odebrat ${name}`}
          // The drag's pointer listeners live on the chip; a click on × is not a drag.
          onPointerDown={(e) => e.stopPropagation()}
          onClick={onRemove}
        >
          ×
        </button>
      )}
    </span>
  );
}
