import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button, ErrorPanel } from "@/ui";

interface Props {
  /** The section's name, for the message. */
  label: string;
  /** A change of this (the route) clears a shown error without remounting the section. */
  resetKey: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Keeps the page usable when a section throws while it renders: the rail, the top bar and the
 * other sections stay, and the section shows what went wrong with "Try again". Moving to
 * another route clears it.
 */
export class SectionBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // qPilot was updated (or rebuilt) while this tab was open: the section's code file has a new
    // name. Reload once to fetch the new page; a second failure within a minute shows the panel.
    if (isStaleCode(error) && reloadOnce()) return;
    // For whoever opens the console: the component stack names the part that failed.
    console.error(
      `qPilot: the ${this.props.label} section failed to show`,
      error,
      info.componentStack,
    );
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="mx-auto mt-6 max-w-2xl">
        <h1 className="mb-3 text-2xl font-semibold tracking-tight">{this.props.label}</h1>
        <ErrorPanel error={error} title={`This part of the page could not be shown`}>
          <p className="mt-2 text-[13px] text-muted">
            Nothing was changed in your study. The rest of the page works; try again, or reload the
            page. If it keeps happening, the message above is what to report.
          </p>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant="primary" onClick={() => this.setState({ error: null })}>
              Try again
            </Button>
            <Button size="sm" onClick={() => window.location.reload()}>
              Reload the page
            </Button>
          </div>
        </ErrorPanel>
      </div>
    );
  }
}

/** True for a failed lazy import: the build this tab loaded is no longer on the server. */
function isStaleCode(error: Error): boolean {
  return /dynamically imported module|Importing a module script failed|error loading dynamically/i.test(
    error.message,
  );
}

/** Reload the page unless it already reloaded for this in the last minute. */
function reloadOnce(): boolean {
  const KEY = "qpilot.staleReloadAt";
  try {
    const last = Number(sessionStorage.getItem(KEY) ?? 0);
    if (Date.now() - last < 60_000) return false;
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    return false; // no storage: show the panel and its "Reload the page" button instead
  }
  window.location.reload();
  return true;
}
