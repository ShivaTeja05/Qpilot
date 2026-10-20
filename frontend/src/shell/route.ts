/**
 * The page's location, parsed once: `#/` (Open), `#/settings`, `#/s/<session>/<section>/…`,
 * `#/r/<study>/<section>/…`. Sections read it with {@link useRoute} and move with
 * {@link useGo}.
 */
import { useLocation } from "wouter";
import { SECTION, type SectionId } from "./sections";

export interface Route {
  /** The section shown ("home" for an unknown path). */
  section: SectionId;
  /** "s" (a Studio session) or "r" (a study analysed outside one); null on global routes. */
  kind: "s" | "r" | null;
  key: string | null;
  /** Segments after the section (e.g. the gene name). */
  rest: string[];
  /** True when the workspace path named no section (the shell picks one). */
  bare: boolean;
  path: string;
}

/** Parse a hash path into a route. */
export function parseRoute(path: string): Route {
  const parts = path
    .split("?")[0]!
    .split("/")
    .filter(Boolean)
    .map((p) => {
      try {
        return decodeURIComponent(p);
      } catch {
        return p;
      }
    });
  const base = { kind: null, key: null, rest: [], bare: false, path };
  if (parts.length === 0) return { ...base, section: "home" };
  if (parts[0] === "settings") return { ...base, section: "settings" };
  if ((parts[0] === "s" || parts[0] === "r") && parts[1] && /^[0-9a-f]{6,64}$/i.test(parts[1])) {
    const [, key, section, ...rest] = parts;
    const known =
      section && section in SECTION && SECTION[section as SectionId].scope === "workspace";
    return {
      section: known ? (section as SectionId) : "results",
      kind: parts[0],
      key: key!,
      rest: known ? rest : [],
      bare: !known,
      path,
    };
  }
  return { ...base, section: "home" };
}

/** The current route. */
export function useRoute(): Route {
  const [path] = useLocation();
  return parseRoute(path);
}

/** The hash path of a section of a workspace given by kind + key. */
export function pathOf(
  kind: "s" | "r" | null,
  key: string | null,
  section: SectionId,
  ...rest: string[]
): string {
  if (SECTION[section].scope === "global" || !kind || !key)
    return section === "home" ? "/" : `/${section}`;
  return ["", kind, key, section, ...rest.map(encodeURIComponent)].join("/");
}

/** Navigate to a section of the current workspace (or a global one). */
export function useGo() {
  const [, navigate] = useLocation();
  const route = useRoute();
  return (section: SectionId, ...rest: string[]) =>
    navigate(pathOf(route.kind, route.key, section, ...rest));
}
