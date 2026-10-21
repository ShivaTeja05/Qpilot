/**
 * The online demo's entry (`npm run build:demo`): the recordings' network layer first, then the
 * page itself. The page is a dynamic import on purpose: the typed client takes `fetch` when it
 * is created, and a static import would let the bundler evaluate the client's chunk before
 * `install` has run.
 */
import "./install";

void import("../main");
