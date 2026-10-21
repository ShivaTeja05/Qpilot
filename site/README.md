# qPilot's read-only online demo

This folder is the static site deployed to Vercel: qPilot's one page (the real build, with
`VITE_STATIC_DEMO=1`), answered from recordings of a real `qpilot app` on the public demo study
(Vermeulen et al. 2009, *Lancet Oncology* 10:663–671; Ruijter et al. 2013, *Methods* 59:32–46;
CC BY 4.0). Nothing in it is mock data, and nothing runs on a server: every number on the page is
the engine's answer, recorded once.

- `vercel.json` — static hosting with qPilot's own strict Content-Security-Policy (`'self'` only:
  no external request of any kind) and the same security headers as `qpilot app`.
- `index.html`, `assets/` — the page (`npm run build:demo` → `frontend/dist-demo/`).
- `demo-api/index.json` — every recorded answer: its key, status, method and path.
- `demo-api/<key>.gz` — one answer (gzipped; the page unpacks it). The key is the SHA-256 of the
  method, the path, the sorted query and the canonical JSON body (`frontend/src/demo/key.ts`).
- `demo-api/curves/<pack>.gz` — every well's raw curve, packed by plate.

## How the page answers

`frontend/src/demo/install.ts` is loaded before the page and replaces `fetch` for `/api/...`:

- a `GET`, or one of the POSTs that only compute (the audit's what-if, Claims, Plan next, Trace's
  "set these samples aside", Ask, the report's files), is answered from its recording;
- anything else (deciding a card, accepting a proposal, opening a file, settings) is refused in
  plain words: *This online demo is read-only. Install qPilot to analyse your own files*;
- a view that was not recorded says so, with the same link.

There is no event stream (the live dot reads "Demo"), Open's file card explains that opening a
file needs qPilot on your own computer, and a slim banner names the study and links to GitHub.
Normal builds (`npm run build`) are byte-identical with or without this code.

## Rebuild, record, check

```bash
cd frontend
npm run build:demo
QPILOT_PYTHON=/path/to/.venv/bin/python \
QPILOT_DEMO_SEED=/path/to/seeded/studies \
  nice -n 10 node scripts/static-demo/record.mjs
```

`QPILOT_DEMO_SEED` is a study store with the demo study walked through Studio (design and curves
confirmed) and audited. The script copies it to a scratch folder, starts `qpilot app` on it (a fixed
key, no model), walks the built page through every section, gene, tab, palette and drawer in
Chromium while recording, writes this folder, then serves it the way Vercel will and walks it
again. It fails if any request has no recording, if any request leaves the site, or on any
console error. Local paths in the answers are rewritten to qPilot's defaults (`~/.cache/qpilot`),
and the script refuses to write the site if a user name or home path is left anywhere.

`node scripts/static-demo/record.mjs --verify` checks the folder as it is;
`node scripts/static-demo/serve.mjs ../site 7961` serves it locally.

## Deploy

```bash
npx vercel@latest deploy site --temporary --prod --yes --verify
```

`--temporary` needs no Vercel account. The command prints the URL and a link to claim the
deployment into an account; once claimed it can be given a project name and a domain.
