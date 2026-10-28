/**
 * The Design editor's routes (`routers/design.py`): the editor's view, the check of a draft
 * (writes nothing) and recording it (always `actor="human"`, set by the server).
 */
import { useQuery } from "@tanstack/react-query";
import { api, postForm, unwrap, type Schemas } from "@/api/client";
import type { EditItem } from "./draft";

export type DesignPlan = Schemas["DesignPlanView"];
export type DesignSet = Schemas["DesignSetView"];

export function useDesignEditor(sid: string | null | undefined) {
  return useQuery({
    queryKey: ["w", sid, "design-editor"],
    enabled: Boolean(sid),
    queryFn: () =>
      unwrap(api.GET("/api/sessions/{sid}/design/editor", { params: { path: { sid: sid! } } })),
    placeholderData: (prev) => prev,
  });
}

export const checkDesign = (sid: string, items: EditItem[]) =>
  unwrap(
    api.POST("/api/sessions/{sid}/design/check", {
      params: { path: { sid } },
      body: { items },
    }),
  );

export const setDesign = (
  sid: string,
  items: EditItem[],
  reason: string,
  expectedHead: string,
  acceptContradicted: boolean,
) =>
  unwrap(
    api.POST("/api/sessions/{sid}/design/set", {
      params: { path: { sid } },
      body: {
        items,
        reason,
        expected_head: expectedHead,
        accept_contradicted: acceptContradicted,
      },
    }),
  );

/** Attach a sample sheet to the session (multipart); the rules then propose again (a job). */
export const attachSheet = (sid: string, file: File) => {
  const form = new FormData();
  form.append("sheet", file, file.name);
  return postForm<Schemas["SheetAttached"]>(`/api/sessions/${sid}/sheet`, form);
};
