import { useDroppable } from "@dnd-kit/core";
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
}

export function Cell({ id, children, colSpan = 1, onMergeRight, onUnmerge }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id });

  function stop<T>(handler: () => T) {
    return (e: MouseEvent) => {
      e.stopPropagation();
      handler();
    };
  }

  return (
    <td ref={setNodeRef} className={`grid-cell${isOver ? " drop-over" : ""}`} colSpan={colSpan}>
      <div className="grid-cell-inner">{children}</div>
      {onMergeRight && (
        <div className="cell-merge-handle" title="Click to merge with the next cell" onClick={stop(onMergeRight)} />
      )}
      {onUnmerge && (
        <button
          type="button"
          className="cell-unmerge-handle"
          title="Click to split this merged cell back apart"
          onClick={stop(onUnmerge)}
        >
          ⊟
        </button>
      )}
    </td>
  );
}
