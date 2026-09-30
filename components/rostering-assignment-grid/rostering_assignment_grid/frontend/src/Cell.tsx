import { useDndContext, useDroppable } from "@dnd-kit/core";
import type { MouseEvent, ReactNode } from "react";

interface Props {
  id: string;
  children: ReactNode;
  colSpan?: number;
  // Present only when this cell has a mergeable neighbor to its right in
  // this specific row (see CLAUDE.md "Out-of-solver roles") — renders a
  // small clickable edge handle.
  onMergeRight?: () => void;
  // Present only when this cell is currently merged (spans more than one
  // room) — renders a small clickable "unmerge" icon.
  onUnmerge?: () => void;
  // The Broken-rule lines this cell is part of, if any — marks it lightly.
  broken?: string[];
  // A manual role's cell (see ManualCell): the drag data its droppable carries,
  // and whether it refuses the drag in flight. A solver-role cell has neither;
  // `disabled` without `dropData` (a manual cell that takes no drops) only needs
  // its unique id.
  dropData?: Record<string, unknown>;
  disabled?: boolean;
  // Whose chips the cell takes: Helpers' (the solver roles and the Additional
  // roles) or Organizers' (the leadership slots) — never both. A drag of the other
  // kind is refused and the cell fades while it is in flight.
  accepts?: "helper" | "organizer";
  // Extra classes, a click on the cell's own background (ManualCell opens its
  // name field there) and a tooltip.
  className?: string;
  onClick?: () => void;
  title?: string;
}

export function Cell({
  id,
  children,
  colSpan = 1,
  onMergeRight,
  onUnmerge,
  broken,
  dropData,
  disabled = false,
  accepts = "helper",
  className,
  onClick,
  title,
}: Props) {
  const { active } = useDndContext();
  const dragKind = active?.data.current?.kind as string | undefined;
  const wrongKind = dragKind !== undefined && dragKind !== accepts;
  const { setNodeRef, isOver } = useDroppable({ id, disabled: disabled || wrongKind, data: dropData });

  function stop<T>(handler: () => T) {
    return (e: MouseEvent) => {
      e.stopPropagation();
      handler();
    };
  }

  return (
    <td
      ref={setNodeRef}
      className={`grid-cell${isOver ? " drop-over" : ""}${broken?.length ? " broken" : ""}${wrongKind ? " drop-disabled" : ""}${className ? ` ${className}` : ""}`}
      colSpan={colSpan}
      title={broken?.length ? broken.join("\n") : title}
      onClick={onClick}
    >
      <div className="grid-cell-inner">{children}</div>
      {onMergeRight && (
        <div className="cell-merge-handle" title="Kliknutím sloučíte s další buňkou" onClick={stop(onMergeRight)} />
      )}
      {onUnmerge && (
        <button
          type="button"
          className="cell-unmerge-handle"
          title="Kliknutím sloučenou buňku opět rozdělíte"
          onClick={stop(onUnmerge)}
        >
          ⊟
        </button>
      )}
    </td>
  );
}
