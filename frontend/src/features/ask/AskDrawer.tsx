import type { Schemas } from "@/api/client";

export interface AskDrawerProps {
  workspace: Schemas["WorkspaceView"] | null;
  open: boolean;
  onClose: () => void;
}

/** The Ask drawer's content (owner: insight). The shell renders it inside its drawer frame. */
export default function AskDrawer(_: AskDrawerProps) {
  return null;
}
