import {
  FrontendRenderer,
  FrontendRendererArgs,
} from "@streamlit/component-v2-lib";
import { StrictMode } from "react";
import { createRoot, Root } from "react-dom/client";

import AssignmentGrid from "./AssignmentGrid";
import type { AssignmentGridData, AssignmentGridState } from "./types";
import "./style.css";

// Handle the possibility of multiple instances of the component to keep
// track of the React roots for each component instance.
const reactRoots: WeakMap<FrontendRendererArgs["parentElement"], Root> =
  new WeakMap();

const AssignmentGridRoot: FrontendRenderer<
  AssignmentGridState,
  AssignmentGridData
> = (args) => {
  const { data, parentElement, setTriggerValue } = args;

  const rootElement = parentElement.querySelector(".react-root");
  if (!rootElement) {
    throw new Error("Unexpected: React root element not found");
  }

  let reactRoot = reactRoots.get(parentElement);
  if (!reactRoot) {
    reactRoot = createRoot(rootElement);
    reactRoots.set(parentElement, reactRoot);
  }

  reactRoot.render(
    <StrictMode>
      <AssignmentGrid {...data} setTriggerValue={setTriggerValue} />
    </StrictMode>,
  );

  return () => {
    const reactRoot = reactRoots.get(parentElement);
    if (reactRoot) {
      reactRoot.unmount();
      reactRoots.delete(parentElement);
    }
  };
};

export default AssignmentGridRoot;
