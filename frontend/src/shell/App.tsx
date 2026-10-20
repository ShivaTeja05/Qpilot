/**
 * The page: one hash router, the rail, the top bar and the current section. Workspace routes
 * are `/s/<session id>/<section>/...` (a Studio session) and `/r/<study id>/<section>/...` (a
 * study analysed outside one).
 */
import { useQuery } from "@tanstack/react-query";
import { Suspense } from "react";
import { Route, Router, Switch, useParams } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import { api, unwrap } from "@/api/client";
import { useLiveEvents } from "@/api/live";
import { SECTION, type SectionId } from "./sections";

function SectionView({ id, workspaceKey, kind, rest }: {
  id: SectionId;
  workspaceKey?: string;
  kind?: "s" | "r";
  rest: string[];
}) {
  const frame = useQuery({
    queryKey: ["w", workspaceKey, "frame"],
    enabled: Boolean(workspaceKey),
    queryFn: () =>
      kind === "s"
        ? unwrap(api.GET("/api/sessions/{sid}", { params: { path: { sid: workspaceKey! } } }))
        : unwrap(api.GET("/api/studies/{study_id}", { params: { path: { study_id: workspaceKey! } } })),
  });
  const Component = SECTION[id].component;
  if (workspaceKey && !frame.data) {
    return frame.error ? (
      <p className="p-10 text-danger">{String((frame.error as Error).message)}</p>
    ) : null;
  }
  return (
    <Suspense fallback={null}>
      <Component workspace={frame.data ?? null} rest={rest} />
    </Suspense>
  );
}

function WorkspaceRoute() {
  const params = useParams<{ kind: "s" | "r"; key: string; "*"?: string }>();
  const [section = "results", ...rest] = (params["*"] ?? "").split("/").filter(Boolean);
  const id = (section in SECTION ? section : "results") as SectionId;
  return <SectionView id={id} workspaceKey={params.key} kind={params.kind} rest={rest} />;
}

export function App() {
  useLiveEvents();
  return (
    <Router hook={useHashLocation}>
      <div className="flex min-h-dvh">
        <main className="min-w-0 flex-1">
          <Switch>
            <Route path="/">{() => <SectionView id="home" rest={[]} />}</Route>
            <Route path="/settings">{() => <SectionView id="settings" rest={[]} />}</Route>
            <Route path="/:kind/:key/*?" component={WorkspaceRoute} />
          </Switch>
        </main>
      </div>
    </Router>
  );
}
