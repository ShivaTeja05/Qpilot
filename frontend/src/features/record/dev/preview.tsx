// Dev-only harness (never committed): the Record and Agents sections with the providers the shell
// will mount, on the real API of this worktree's store.
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@/styles.css";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { Route, Router, Switch, useParams } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import { api, unwrap } from "@/api/client";
import { useLiveEvents } from "@/api/live";
import { Toaster, TooltipProvider } from "@/ui";
import RecordSection from "../index";
import AgentsSection from "@/features/agents";
import recordedChain from "../recorded/decisions-e300000d4f9a.json";

// Until GET /decisions lands: answer it with the chain recorded from this store.
const realFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const res = await realFetch(input, init);
  if (res.status === 404 && String(input).endsWith("/api/studies/e300000d4f9a/decisions")) {
    return new Response(JSON.stringify(recordedChain), { headers: { "content-type": "application/json" } });
  }
  return res;
};

function View() {
  useLiveEvents();
  const p = useParams<{ key: string; section: string }>();
  const frame = useQuery({
    queryKey: ["w", p.key, "frame"],
    queryFn: () => unwrap(api.GET("/api/sessions/{sid}", { params: { path: { sid: p.key } } })),
  });
  if (!frame.data) return null;
  return p.section === "agents" ? <AgentsSection workspace={frame.data} rest={[]} /> : <RecordSection workspace={frame.data} rest={[]} />;
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={new QueryClient()}>
    <TooltipProvider>
      <Router hook={useHashLocation}>
        <Switch>
          <Route path="/s/:key/:section" component={View} />
        </Switch>
      </Router>
      <Toaster />
    </TooltipProvider>
  </QueryClientProvider>,
);
