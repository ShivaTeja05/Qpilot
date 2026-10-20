# qPilot: a scientist's guide to the page

qPilot reads your qPCR instrument's raw amplification curves, analyses every plate the same way, and shows you which of your analysis choices could change a conclusion. **The AI proposes. The engine checks. You decide.** This guide walks through the page section by section: what to look at, what each word on it means, and what to do next. For research use only; not for clinical or diagnostic use.

The page runs on your computer. It sends nothing anywhere unless you press a button that says so (downloading the demo study, or asking a model you configured). Everything below was checked against the demo study, 64 plates of neuroblastoma tumours (Vermeulen et al. 2009, Ruijter et al. 2013); the numbers quoted come from running qPilot on it.

## Contents

1. [Start the page](#1-start-the-page)
2. [How the page is laid out](#2-how-the-page-is-laid-out)
3. [Three scales you will see everywhere](#3-three-scales-you-will-see-everywhere): call, level, verdict
4. [Open](#4-open)
5. [Design (blind)](#5-design-blind)
6. [Curves (blind)](#6-curves-blind)
7. [Results](#7-results)
8. [Gene](#8-gene)
9. [Audit](#9-audit)
10. [Prism](#10-prism)
11. [Record](#11-record)
12. [Agents](#12-agents)
13. [Ask](#13-ask)
14. [Settings](#14-settings)
15. [Keyboard](#15-keyboard)
16. [When something does not work](#16-when-something-does-not-work)
17. [What the page never does](#17-what-the-page-never-does)

## 1. Start the page

```bash
qpilot app
```

qPilot prints a link that starts with `http://127.0.0.1:` and opens it in your browser. **Use that link:** it carries a key that belongs to this launch, which is what lets your browser, and nobody else, use the page. Another program, another user of this computer, or a web page in your browser cannot use the page without it. If you close the tab, open the link again from the terminal. Stop qPilot with Ctrl-C in that terminal.

* The page is on port 7860, or the next free one (`--port N` chooses). It answers only on `127.0.0.1` / `localhost`.
* Your work is kept in the study store (`~/.cache/qpilot/studies`, or the folder in `QPILOT_STUDIES_DIR`), the same store `qpilot serve` (agents) uses, so a decision made by an agent shows up on the page within about a second.
* `qpilot app --fresh-demo` moves earlier demo work aside (kept, never deleted) and starts the demo clean.
* A second `qpilot app` has its own key. If you open both in one browser, the newest link replaces the earlier launch's key and the earlier tab asks you to open its link again.

## 2. How the page is laid out

* **The rail (left).** The workflow in order: **Design → Curves → Results → Audit → Prism → Record**. Each step shows where it stands: a check when it is confirmed (for the Audit: when it has been run), a count of the proposals or requests waiting for you, or a lock with the reason in words, for example "Confirm the design first", "Blind until the design and the curves are confirmed" or "Decide the analysis choices first". Below the workflow: **Agents** and **Settings**. At the top, the workspace switcher lists your recent studies (⌘O opens a file). On a narrow window the rail shrinks to icons, and on a phone it becomes a bar at the bottom.
* **The top bar.** The study's title and, on a wide window, the start of its input file's SHA-256 (click to copy). The **chain pill** (`chain 3f2a…`, or `chain empty` before any decision) shows the head of the decision chain; click it to open the Record. The **model chip** says `no model`, `local <name>` or `REMOTE — names pseudonymised`, with a dot for whether the model is answering, being checked, or not answering (hover for the reason; click for Settings). The **autonomy switch** (Suggest · Decide and tell me; on a narrow window it is in the menu at the right). The **agent bell** (requests waiting for you and work that is running). **Ask your data** (⌘J). **Go to…** (⌘K, the command palette). The theme toggle (system, light, dark). The **live dot**: green means the page is connected to qPilot and changes made by an agent or another tab appear within a second; otherwise it says it is reconnecting.
* **⌘K** opens the palette: go to a section, a gene or a study, or run an action: **Propose the design**, **Confirm this stage**, **Check the curves**, **Run the audit**, **Send to Prism**, **Export the Analysis Record**, **Verify a record**, **Ask your data**. Actions that are not reachable yet are not offered.
* **The next-step banner** under the top bar says what to do next in this workspace ("Next: Decide 3 analysis choices"), with a button that goes there and puts the cursor on the action.
* **Ask** (the right-hand drawer, ⌘J): ask a question of the open study in plain words.
* **Slow work** (checking curves, running the audit) appears as a card that says what qPilot is doing, how long it has taken and how long it usually takes ("usually about 50 s"). You can move to another section; it keeps running, and the bell lists it.
* **Every change you make** brings a short message saying what happened, with **Undo** where the record allows it.

A *workspace* is one study at a time. Opening a file creates a **Studio session** (the sections Design, Curves, Results, … in that order). A study that was analysed outside the page (by `qpilot run`, or by an agent) is also a workspace; it has no Design or Curves, and its Results show straight away.

## 3. Three scales you will see everywhere

**A call** is what the analysis concludes about a gene: **▲ up**, **▼ down** or **— no call**. The rule is fixed and printed on the Results page: a gene is called up or down only if p < 0.05 **and** the change is at least 2-fold. A gene that does not meet both is "no change called", which is not the same as "no change".

**A level** says how far to trust one gene's result: **High**, **Moderate**, **Low**, **Very low** (four bars, three, two, one). It is never a percentage. A gene starts at High and moves down one level for each of three checks it fails:

* *precision*: its 95 % confidence interval crosses the 2-fold line;
* *robustness*: its call holds in fewer than 80 % of the reasonable analyses;
* *normalisation*: fewer than two control genes are stable by geNorm (M below 1.5), or no V(n/n+1) is below 0.15.

It moves up one level only when the change is at least 4-fold (or at most a quarter), the call holds in every reasonable analysis, and the precision and normalisation checks pass. The reasons are always listed beside the level, in words. Three more facts are reported but do not change the level: how few choices at once flip the call, the assay's efficiency and undetermined wells, and the smallest change your design could detect.

**A verdict** (only after the audit has run) is the audit's reading of one gene, in six words:

| Verdict | In plain words |
|---|---|
| **Solid** | The same call in at least 95 of 100 reasonable analyses, no 5 or fewer samples change it, and the difference is clear in at least 95 of 100. |
| **Holds with caveats** | The same call in at least 95 of 100, but 5 or fewer samples change it, or the difference is not always clear. |
| **Depends on your choices** | The same call in 80 to 95 of 100; the rest depend on the choices made. |
| **Fragile** | The same call in fewer than 80 of 100, or 2 or fewer samples change it, or it sits very close to the fold-change line. |
| **Check data first** | A problem found in the data changes this call when it is fixed. |
| **No change called** | Not called a change (see the rule above). |

Every one of these has a shape and a word as well as a colour, so none depends on colour alone. **Holds** (for example "holds 64 %") is a robustness fraction: the share of reasonable analyses that give the gene the same call. It is not a probability that the call is right. Two sets of analyses are in play and the page says which: on **Results** and **Gene**, the reasonable analyses qPilot itself runs (744 on the demo: 31 sets of control genes × 3 group cut-offs × 2 ways of treating empty wells × 4 rules for which curves count as amplified); in the **Audit**, the audit's own *defensible* analyses (144 on the demo, out of the 90,396 it runs in all).

## 4. Open

The first screen. It says what qPilot does in four steps (the AI proposes; the engine checks; you decide; the record keeps it) and offers three things:

* **Open your RDML file.** Drop the instrument's RDML export on the box, or press **Choose a file…** (⌘O does the same anywhere). RDML (`.rdml` or `.xml`) is the instrument-neutral format most qPCR software can write. You may add a **sample sheet** (`.xlsx` or `.csv`) and **one sentence about the experiment**, for example "LPS versus PBS, three mice each" (at most 500 characters; the AI reads it when it proposes the design, and it is never obeyed as an instruction). Then press **Open this file**. Opening reads the file and quarantines every name in it; it analyses nothing and proposes nothing yet, and the file stays on this computer.
* **Open the demo study.** A public neuroblastoma study (Vermeulen et al. 2009, Ruijter et al. 2013), to see every step on real data before you open your own. The card shows the study, its licence and its SHA-256. If the file is not on your computer yet, the button reads **Download 7.0 MB and open**, and the card says where it comes from (the RDML consortium's repository, at a pinned commit, checked against its SHA-256 before it is used). That is the only thing this screen downloads, and only when you click. Once the demo has been opened the card says **Continue the demo study** and your work on it is kept; to start again from a clean study, use **Start a fresh demo** in Settings.
* **Recent.** Your earlier workspaces, the most recently changed first, with a filter box. Each card shows the title, the file, plates · samples · genes, a chip for each stage (confirmed, or how many proposals wait), the number of decisions recorded, when it was last changed, and badges: **Demo**, **Audited**, **Analysed outside Studio** (results are shown straight away, with no blind stages), the number of agent requests waiting for you, and **File missing or changed** when the original file is no longer where it was.

At the bottom: the qPilot version, the model chip (click for Settings), the vendored curve method and its commit, the line that says what can leave this machine (the same as `qpilot doctor`), and whether the robustness audit is installed.

## 5. Design (blind)

*Blind* means that until you have confirmed the design **and** the curves, the page shows nothing that pairs a group with a number: no fold change, no p-value, no direction of change. The server refuses to send it. This keeps your choices of groups and controls from being steered by the result you hope for.

**What to do.** Press **Propose the design** (about 9 seconds on the demo). qPilot's rules, and a language model when one is configured, read your file, your sheet and your sentence and propose how to read the plates: which samples are standards, controls or study samples (and what each control is), which are groups, which samples are the same biological unit, which genes are references, which two groups to compare. Each proposal is a card in the inbox on the left, the ones the engine **contradicts** first. On the right, the **plate map** shows each plate's wells coloured by their declared type; hover for the original text of a name, and a name that reads like an instruction is marked and never obeyed.

**A proposal card has six parts:**

1. *The proposal*, in words, and the other readings that were considered.
2. *Why*: each piece of evidence folds out: the text from your file with where it came from, a cell of your sheet, or a well (which opens its curve).
3. *Engine check*: **Consistent** (the engine found nothing that refutes it; a check can refute, never prove), **Contradicted** (it refutes it, with the rule and numbers; accepting it anyway needs a reason), or **Cannot check** (decide it on the evidence).
4. *Consequence*: hidden in the blind stages, except "this matters for at least one conclusion", or press **Does this matter?** to have the engine run the design both ways and answer only yes or no.
5. *Level*, with reasons (never a percentage).
6. **Accept**, **Edit** (change the fields, then it is checked again) or **Reject** (a reason is required). The footer says who made it: a fixed rule, a model (with its name and prompt hash) or an agent.

**Many at once.** **Accept all consistent…** shows the exact list first; a second click accepts exactly that list, one record entry each. A contradicted or cannot-check proposal is never on it. **Reject contradicted AI calls…** does the same for model and agent proposals the engine contradicts, with one reason you type.

**Confirm this stage…** shows what the confirmation covers; **Yes, confirm** confirms. When every proposal is settled and you have confirmed, the Curves section opens.

*On the demo:* the rules make 131 proposals; 121 are consistent and 9 are contradicted (seven competimer standards that never amplified, one competimer series, and one standard series whose R² is only 0.694). Reject those nine with a reason, accept the rest, confirm.

## 6. Curves (blind)

Opens when the design is confirmed (until then it is locked: "Confirm the design first"). Press **Check the curves** (about 15 seconds on the demo; afterwards it reads **Check the curves again**). qPilot fits every curve with LinRegPCR and a second, learned reader (the *Curve Judge*) classifies each as amplified or not. Wherever the two disagree **and it could change a conclusion**, you get a proposal card (a well call), and a card for the call rule you want to use. Accept, edit or reject them exactly as in Design, then confirm the stage.

* **The curves stage** card says which rule is in use ("LinRegPCR's call (the engine's default), until you accept a rule"), how many proposals you have accepted, rejected and have waiting, and lists the waiting ones with their engine check and level; **Open the curve** takes you to the well a proposal is about.
* **The plate** shows every well of one plate. Choose the **Gene** and the **Plate** (`[` and `]` step through the plates), and **Colour the wells by** *Sample type*, *Amplification call*, *Cq*, *Efficiency* or *R²*. The number and call layers are available once the design is confirmed; a well where the Curve Judge reads the curve differently is outlined, and a corner mark shows a call a person set. Pick one well, or several, on the plate.
* **The curve** shows the raw fluorescence by cycle of the wells you picked, with a linear/log switch. For one well it also gives its Cq, efficiency, R² and baseline, and how the well is called under each amplification rule; for several wells, a table with each one's LinRegPCR call, Curve Judge call, Cq and efficiency. The first curve can take a few seconds, because it is read from your file.

There is no group, fold change or p-value anywhere on this screen.

*On the demo:* the Curve Judge disagrees with LinRegPCR on 166 study wells; only 110 early curves of one reference gene (ALUsq) could change a conclusion, and LinRegPCR contradicts each of them with a complete fit. Reject them with one reason, keep LinRegPCR's call rule, confirm. The learned reader is validated only on the demo's instrument (LightCycler 480, SYBR Green I); on another file it is a second opinion at most.

## 7. Results

Opens once the design and the curves are confirmed; qPilot then analyses your confirmed design (about 30 seconds on the demo).

**The summary strip:** plates, reactions, samples, the groups and how many biological units each has, the conclusion rule, and the reference genes with their geNorm stability (M, V).

**The robustness map.** One point per gene. Left–right: fold change (log scale, labelled in ×). Up–down: the share of reasonable analyses that give the same call. Colour and shape: the call and the level. The 2× lines mark the rule. A gene far from the lines and high on the map is a result that does not depend on your choices; a gene near a line, or low, does. Click a point to open the gene; **View as table** gives the same numbers as text.

**All genes** is a table you can sort and filter by call, level, or "flips" (genes whose call at least one choice changes): gene, call, fold change [95 % CI], p, holds, level, reasons.

**The flip matrix** has the decisions as rows and the genes as columns; a mark means that choice alone flips that gene's call.

**Decision Cards (right column).** One card per choice that could change a conclusion, ranked by how many conclusions it can change: *which control genes*, *where to cut the groups*, *what to do with empty wells*, *which curves count as amplified*. Each card shows the question, the evidence, each option and what it changes for the headline genes, and the recommended option. Choose an option, write a reason (required), press **Decide**. It goes into the record with your name as the actor, and the analysis updates.

* A card where **no option changes any conclusion** is decided automatically, using the recommended option, and logged as the system; you can reopen it.
* A choice that **can** flip a conclusion is yours alone: an agent, a model or the system can only ask, and the request waits at the top as **Approve** / **Turn down**.
* A decided card folds up showing who decided and why. **Undo** adds a new entry to the record (nothing is erased).
* **Explain with the model** (only when a model is answering) writes a plain explanation whose every number is a fact qPilot computed; the numbers are cited, and if the model writes a number of its own, qPilot discards the text and shows its own.

*On the demo:* ODC1 is called up at 3.59× under the recommended choices; the usual Excel route (2^-ΔΔCq with a t-test on the linear scale) would change 14 of the 58 conclusions.

## 8. Gene

Open a gene from the Results map or table. `[` and `]` go to the previous and next gene.

The header gives the call, the fold change with its 95 % confidence interval, p, the number of samples per group, the level with its reasons, and (after an audit) the verdict. Then, top to bottom:

* **What holds.** The share of reasonable analyses with the same call, and a strip with every reasonable analysis as a dot on the fold-change axis, coloured by call. A strip spread across the 2× line is a gene whose call depends on your choices.
* **One choice at a time.** For each decision, a dot per option: change only that choice and see where the fold change lands.
* **Your samples.** Each sample as a dot, by group. Click one to open its well and its curve: an outlier is a place to look, not yet a reason to remove it.
* **What changes it, what it leans on, what to do** (after an audit): the choices that flip it, the control genes and samples it depends on, and what to check or fix.
* **The Decision Cards that affect this gene**, **the assay and its wells** (efficiency, Cq range, undetermined wells), the **reference-gene stability** bars, and the Prism figure for this gene when it exists.

## 9. Audit

The audit re-runs your **confirmed** study under every combination of eight analysis decisions (efficiency model, flagged wells, late Cq, empty wells, which control genes, where to cut the groups, which test, correction for many genes): 90,396 analyses on the demo, about 50 seconds. It first checks that its own baseline reproduces qPilot's results gene by gene; if it does not, it refuses and writes nothing. It then gives each gene one of the six verdicts of [section 3](#3-three-scales-you-will-see-everywhere). A verdict counts only the options the audit marks *defensible* (144 analyses on the demo); the other options are there so that you can see how far a choice would take a result. Two of the decisions, where to cut the groups and the correction for many genes, change the claim rather than the analysis, and are reported separately.

* **Not run yet:** the page says what the audit is and offers **Run the audit** (a job with stages).
* **Not applicable:** a design with technical replicates, today, because the audit needs one well per sample and gene. The page says so in words.
* **Done:** four tabs.
  * **Study:** the verdict counts, the map, the calls that one choice changes, how much of the spread each decision explains, reference-gene stability, "fix these first", and the queue of data issues it found (wells, samples, plates).
  * **What-if lab:** one menu per decision, grouped by how defensible the options are; the dumbbell shows every gene from the planned analysis to your chosen one, changed genes first. Nothing is stored and nothing is decided here.
  * **How it works:** the stages, the verdict rules, the known-answer tests and the audit's limits.
  * **Verify:** the audit's checksums and whether it is bound to the current decision record. If a decision changed after the audit, it is stale and the page says to run it again.

## 10. Prism

For people who finish their figures in GraphPad Prism. qPilot does not replace Prism and is not affiliated with GraphPad Software or Dotmatics.

* **Routes** shows how often the usual Excel-to-Prism routes would change a conclusion on this study.
* **The preview** has the tables, the test and the figure (every biological unit, the group means with their 95 % confidence intervals): an approximation of what Prism will draw.
* **Draft the Prism project** makes a proposal like any other: accept it first.
* **Send to Prism** writes a bundle (one table per gene, a script, provenance) into a new folder and offers it as a zip. It starts Prism only if Prism is installed, and says so if not. The script follows GraphPad's documentation but **has not yet been run in a real Prism**, and Prism's template files must be made once by hand ([prism.md](prism.md)).
* **Round trip.** After you change something in Prism (for example leave out a sample), pick the bundle and the folder Prism saved into. Each change comes back as a question with its consequence, computed by qPilot: "Reason?" and, for example, "ODC1 3.590× → 3.319×, still up; 0 of 58 conclusions change". When several samples are excluded, each card also shows what they do together; one at a time may change nothing while together they change a call. Accepting one re-runs the analysis. A question that is out of date says so and cannot be accepted until you read the folder again.

## 11. Record

The decision chain as a timeline: every entry has its sequence number, the card and the option, who decided (a person, an agent or the system), the reason, the time, its hash and the previous entry's hash, and its status (applied, waiting, turned down, out of date).

* **Export the Analysis Record** writes one zip: your input file (when it is still on disk), the results, the cards, the grid of analyses, the facts every sentence cites, the design, every decision with its reason and actor, the versions, and a list of checksums. The page then shows the record's id and chain head and the file to download.
* **Verify a record** takes a zip (yours, or one you received) and checks its checksums, the decision chain, and, if there is one, the audit bound to it.
* The page also gives the two commands to repeat the checks outside it: `qpilot verify <record.zip>` and `qpilot rerun <unzipped folder>` (re-analyses the input and compares the results byte for byte).

The chain is **tamper-evident, not tamper-proof**: nothing is signed, so someone who rewrites every hash consistently is not detected unless you compare the record's id with a copy kept elsewhere. qPilot is not a 21 CFR Part 11 system.

## 12. Agents

For agents that work with qPilot over MCP (Claude Code, for example):

```bash
claude mcp add qpilot -- qpilot serve
```

The page shows this command (with a copy button), the tools an agent has (read, ask, propose; **none can decide a choice that changes a conclusion**), a live list of requests waiting for you (the same **Approve** and **Turn down** as on Results), and the recent entries agents made in the record and in the proposal inbox. The agent bell in the top bar counts the waiting requests. An agent that can run commands as you can still act as you; give agents MCP access, not your shell.

## 13. Ask

Press ⌘J (or the Ask button) and ask the open study a question in plain words, for example "Is ODC1 up, and does it depend on the reference genes?". Every answer says which tool answered it, who wrote the words (a template or the model) and the facts it cites. Numbers in an answer are facts qPilot computed; text that contains a number the engine did not produce is discarded. Asking to *change* a choice does not change it: it goes to the person (you).

## 14. Settings

* **Model.** The provider (none, a local OpenAI-compatible server, or Anthropic) comes from the environment (`QPILOT_MODEL_PROVIDER` and the other variables in [agents.md](agents.md)); the page shows its status and reason, **Check connection**, and **Test this model**, which scores the model on your study (correct answers, invented numbers caught, safety, fallbacks, latency). The page has no field for an endpoint or a key, on purpose.
* **Autonomy.** *Suggest* (the default): the in-page model only suggests. *Decide and tell me*: the in-page model may also apply choices that cannot change any conclusion, and tells you. A choice that can change a conclusion always waits for you, at either setting.
* **Theme**, **Start a fresh demo** (moves earlier work aside), the "what qPilot never does" lines and the version.

## 15. Keyboard

| Keys | Action |
|---|---|
| ⌘K / Ctrl K | Command palette: go to a section, gene or card; actions such as Propose, Run the audit, Export |
| ⌘J | Ask drawer |
| ⌘O | Open a file |
| `g` then `d` / `c` / `r` / `a` / `p` / `e` | Design / Curves / Results / Audit / Prism / Record |
| `j` / `k` | Next / previous card (the inbox, the Decision Cards) |
| `a` / `e` / `x` | Accept / Edit / Reject the focused proposal |
| `[` / `]` | Previous / next gene |
| `Enter`, then ⌘Enter | On a Decision Card: focus the reason, then decide |
| `?` | Shortcut sheet |

Everything can also be done with the Tab key, and every control shows where the focus is.

## 16. When something does not work

| You see | What it means | What to do |
|---|---|---|
| "Open the link qPilot printed in your terminal" | This tab does not carry this launch's key (the page was restarted, or opened by typing the address) | Open the link from the terminal where `qpilot app` runs |
| "Something was decided since you loaded this" | Another tab or an agent changed the record while you were reading | Read the current state shown and decide again |
| A section is locked | The step before it is not confirmed | The lock says which one |
| "The demo study is not downloaded yet" | The demo is not on this computer | Click **Download 7.0 MB and open** on Open, or run `qpilot fetch-demo` |
| The audit is refused | Its baseline does not reproduce qPilot, or the design has technical replicates | The page gives the reason in words |
| The model chip says "not answering" | The model is configured but does not answer; hover for the reason | Rules answer alone meanwhile; check the endpoint and name |
| The live dot is not green | The page lost its connection to qPilot | It reconnects by itself; if not, is `qpilot app` still running? |

## 17. What the page never does

* It never makes a choice that can change a conclusion; those always wait for a person.
* It never shows a group difference (fold change, p-value, direction) before the design and the curves are confirmed, and the server, not the page, enforces this.
* It never shows a number the engine did not compute: there are no sample numbers, no placeholder genes, no example charts.
* It never loads anything from the internet and never sends your data anywhere on its own.
* It never records a decision as anyone but the person at the page.
* It never claims a confidence in percent: levels are ordinal, with reasons.
