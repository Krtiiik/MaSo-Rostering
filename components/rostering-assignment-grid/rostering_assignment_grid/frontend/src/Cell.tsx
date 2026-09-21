import { useDroppable } from "@dnd-kit/core";
import type { ReactNode } from "react";

interface Props {
  id: string;
  children: ReactNode;
}

export function Cell({ id, children }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <td ref={setNodeRef} className={`grid-cell${isOver ? " drop-over" : ""}`}>
      <div className="grid-cell-inner">{children}</div>
    </td>
  );
}
