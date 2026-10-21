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
18. [What this study cannot tell you](#18-what-this-study-cannot-tell-you) (Results)
19. [Where to look](#19-where-to-look) (Trace)
20. [Run Review and the Excel workbook](#20-run-review-and-the-excel-workbook) (Report)
21. [Sheet check](#21-sheet-check)
22. [Instruments](#22-instruments)
23. [RT replicates and run files on Controls](#23-rt-replicates-and-run-files-on-controls)

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
* **The top bar.** The study's title and, on a wide window, the start of its input file's SHA-256 (click to copy). The **chain pill** (`chain 3f2a…`, or `chain empty` before any decision) shows the head of the decision chain; click it to open the Record. The **model chip** says `no model`, `local <name>` or `REMOTE — names pseudonymised`, with a dot for whether the model is answering, being checked, or not answering (hover for the reason; click for Settings). The **autonomy switch** (Suggest · Decide and tell me; on a narrow window it is in the menu at the right) sets what agents that connect over MCP may do on their own in *this study*: see [Agents](#12-agents). The **agent bell** (requests waiting for you and work that is running). **Ask your data** (⌘J). **Go to…** (⌘K, the command palette). The theme toggle (system, light, dark). The **live dot**: green means the page is connected to qPilot and changes made by an agent or another tab appear within a second; otherwise it says it is reconnecting.
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
* *robustness*: its call holds in fewer than 80 % of the analyses qPilot checks (qPilot's choice grid, below);
* *normalisation*: fewer than two control genes are stable by geNorm (M below 1.5), or no V(n/n+1) is below 0.15.

It moves up one level only when the change is at least 4-fold (or at most a quarter), the call holds in every analysis qPilot checks, and the precision and normalisation checks pass. The reasons are always listed beside the level, in words. Three more facts are reported but do not change the level: how few choices at once flip the call, the assay's efficiency and undetermined wells, and the smallest change your design could detect.

**A verdict** (only after the audit has run) is the audit's reading of one gene, in six words:

| Verdict | In plain words |
|---|---|
| **Solid** | The same call in at least 95 % of the audit's reasonable analyses, no 5 or fewer samples change it, and the difference is clear in at least 95 % of them. |
| **Holds with caveats** | The same call in at least 95 %, but 5 or fewer samples change it, or the difference is not always clear. |
| **Depends on your choices** | The same call in 80 to 95 %; the rest depend on the choices made. |
| **Fragile** | The same call in fewer than 80 %, or 2 or fewer samples change it, or it sits very close to the fold-change line. |
| **Check data first** | A problem found in the data changes this call when it is fixed. |
| **No change called** | Not called a change (see the rule above). |

Every one of these has a shape and a word as well as a colour, so none depends on colour alone.

**Two sets of analyses, never confused.** "Holds" is a robustness fraction: the share of a set of analyses that give the gene the same call. It is not a probability that the call is right, and the page always says which set and how many:

* **qPilot's choice grid** (Results, Gene, Ask, the Decision Cards): "holds in 65 % of the 744 analyses qPilot checks". It is every combination of the choices on the Decision Cards: every control-gene set (single genes included), group cut-off, rule for empty wells and rule for which curves count as amplified (31 × 3 × 2 × 4 = 744 on the demo).
* **The audit's reasonable set** (Audit, verdicts, the gene card): "same call in 144 of 144 of the audit's reasonable analyses". It leaves out shortcuts such as single or paired control genes, and holds the group cut-off and the correction for many genes as planned; the audit also runs the full grid of 90,396 so you can see how far a choice would take a result.

The two answer different questions, so they differ: on the demo NM23A's call holds in 65 % of qPilot's 744 analyses and in all 144 of the audit's reasonable set. On the Gene page both appear, each labelled.

## 4. Open

The first screen. It says what qPilot does in four steps (the AI proposes; the engine checks; you decide; the record keeps it) and offers three things:

* **Open your RDML file.** Drop the instrument's RDML export on the box, or press **Choose a file…** (⌘O does the same anywhere). RDML (`.rdml` or `.xml`) is the instrument-neutral format most qPCR software can write. You may add a **sample sheet** (`.xlsx` or `.csv`) and **one sentence about the experiment**, for example "LPS versus PBS, three mice each" (at most 500 characters; the AI reads it when it proposes the design, and it is never obeyed as an instruction). Then press **Open this file**. Opening reads the file and quarantines every name in it; it analyses nothing and proposes nothing yet, and the file stays on this computer.
* **Open the demo study.** A public neuroblastoma study (Vermeulen et al. 2009, Ruijter et al. 2013), to see every step on real data before you open your own. The card shows the study, its licence and its SHA-256. If the file is not on your computer yet, the button reads **Download 7.0 MB and open**, and the card says where it comes from (the RDML consortium's repository, at a pinned commit, checked against its SHA-256 before it is used). That is the only thing this screen downloads, and only when you click. Once the demo has been opened the card says **Continue the demo study** and your work on it is kept; to start again from a clean study, use **Start a fresh demo** in Settings.
* **Recent.** Your earlier workspaces, the most recently changed first, with a filter box. Each card shows the title, the file, plates · samples · genes, a chip for each stage (confirmed, or how many proposals wait), the number of decisions recorded, when it was last changed, and badges: **Demo**, **Audited**, **Analysed outside Studio** (results are shown straight away, with no blind stages), the number of agent requests waiting for you, and **File missing or changed** when the original file is no longer where it was.

At the bottom: the qPilot version, the model chip (click for Settings), the vendored curve method and its commit, the line that says what can leave this machine (the same as `qpilot doctor`), and whether the robustness audit is installed.

## 5. Design (blind)

*Blind* means that until you have confirmed the design **and** the curves, the page shows nothing that pairs a group with a number: no fold change, no p-value, no direction of change. The server refuses to send it. This keeps your choices of groups and controls from being steered by the result you hope for. The header of this screen says "Blind stage 1 of 2".

**What to do.** Press **Propose the design** (about 9 seconds on the demo). qPilot's rules, and a language model when one is configured, read your file, your sheet and your sentence and propose how to read the plates: which samples are standards, controls or study samples (and what each control is), which are in which group, which samples are the same biological unit, which genes are references, which gene each target is, which two groups to compare. You may type one sentence about the experiment here (leave it empty to use the one given when the file was opened). **Propose the design again** reads the file again: new proposals join the inbox, what you already decided stays decided, and a repeat of a decided proposal is refused.

**The inbox** lists one card per proposal, the ones the engine **contradicts** first. Filter it by engine check (all waiting, consistent, contradicted, cannot check) or by kind of proposal, or find a sample or target by name. **The plate map** shows each plate's wells coloured by their declared type (**View as table** gives the same as text); click a well for the names in it, quoted from your file, and the proposals about it. A name that reads like an instruction is marked and never obeyed. **The file** card lists what the file declares (the sample sheet, the sample types and how many of each); nothing is analysed yet.

**A proposal card** shows the proposal in words and, below it, the other readings that were considered, then four parts you can open:

1. **Why**: each piece of evidence: the text from your file with where it came from, a cell of your sheet, or a well (which opens its curve).
2. **Engine check**: **Consistent** (the engine found nothing that refutes it; a check can refute, never prove), **Contradicted** (it refutes it, with the rule and the numbers), or **Cannot check** (decide it on the evidence).
3. **Consequence**: hidden in the blind stages, except "This matters for at least one conclusion; decide on the evidence." On a design proposal that has another reading, press **Does this matter?** to have the engine run the design both ways: it answers only "this matters" or "neither reading changes any conclusion".
4. **Level**: an ordinal level with its reasons (never a percentage).

Then **Accept**, **Edit** (change the fields; the engine checks the edit, then you accept it) or **Reject** (a reason is required). If the engine contradicts a proposal the button reads **Accept anyway…** and asks you to say why. The footer says who made the proposal: a fixed rule, a model (with its name and prompt hash) or an agent.

**Many at once.** **Accept all consistent…** shows the exact list first; **Accept these N** accepts exactly that list, one record entry each. A contradicted or cannot-check proposal is never on it. **Reject contradicted AI calls…** does the same for model and agent proposals the engine contradicts, with one reason you type.

**Confirm this stage…** is offered when every proposal is decided (until then it says how many are waiting). It shows exactly what the confirmation covers: "Confirming freezes this design. The curves stage opens next; results stay hidden until the curves are confirmed too." **Yes, confirm** confirms. A later decision on a design proposal re-opens the stage.

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

**The summary strip:** plates, reactions, samples, the groups and how many biological units each has, genes compared, calls under the rule (how many up, down, no call), the reference genes with their geNorm stability, and whether the robustness audit has run ("Audited at the current decisions", or "Decisions changed since the audit: run it again to bring it up to date").

**The robustness map.** One point per gene. Left–right: fold change (log scale, labelled in ×). Up–down: the share of the analyses qPilot checks (qPilot's choice grid) that give the same call. The 2× lines mark the rule. A gene far from the lines and high on the map is a result that does not depend on your choices; a gene near a line, or low, does. **Colour the genes by** the call, the confidence level or, after an audit, the audit verdict. Hover or use the arrow keys to read a gene; click it, or press Enter, to open it. The chart has a table version for reading the same numbers as text.

**All genes** is a table you can sort and filter: find a gene by name, and filter by call, by confidence, by audit verdict, or to **only genes one choice can flip**. Each row gives the gene, its call, the fold change with its 95 % confidence interval, p, the share of the analyses qPilot checks with the same call ("Same call in"), the confidence level and why ("Why this level").

**What one choice alone can flip** is the flip matrix: each row is a decision on a Decision Card, each column a gene (the genes that flip most first); a darker cell means more of that decision's other options change the gene's call. Decide those cards before you report the genes they flip.

**Decision Cards** (the right-hand column). One card per choice that could change a conclusion, ranked by how many conclusions it can change: *which control genes*, *where to cut the groups*, *what to do with empty wells*, *which curves count as amplified*. A counter says how many are decided. Each card shows the question, the evidence and each option with what it changes for the headline genes; one option is marked **Recommended**, and an option that is not advisable (for example a single control gene) is marked **Not recommended (MIQE)**. Choose an option, write a reason (required, at most 500 characters; it goes into the Analysis Record), and press **Decide: <option>**. The analysis updates.

* A card where **no option changes any conclusion** is decided automatically, with the recommended option, and shows **Decided automatically**; you can reopen it.
* A choice that **can** flip a conclusion is yours alone: an agent, a model or the system can only ask. An agent's request waits on the card as **Agent request**, with the option it asked for marked **Agent asked**; give a reason and press **Approve: <option>** or **Turn down**.
* A decided card shows who decided and why. **Undo: back to <option>** needs a reason and adds a new entry to the record (nothing is erased).
* **Leaving a well out after the curves are confirmed** (from Prism, Controls or the Curves inbox), or putting it back, analyses the file again (so does switching the efficiency models on or off, below). Your choices on the cards come with you: each is written into the new analysis as a new entry that names the earlier analysis and the entry you made there, and the card shows **Carried**. A choice that matters more in the new analysis (it can now change a conclusion, or more of them, where it could not before) is not carried: its card says what you chose before and asks again. Confirm the analysis choices again; it is one click when every card is decided.
* **Explain with the model** (shown only when a model is configured) writes a plain explanation whose every number is a fact qPilot computed and cites; if the model writes a number of its own, qPilot discards the text and shows its own.
* `j` and `k` move between cards, `Enter` puts the cursor in the reason, and ⌘Enter (Ctrl Enter) decides.

**Also test efficiency models** (under the cards). qPilot turns each Cq into a quantity with LinRegPCR's mean efficiency of each assay on each plate. Other choices are defensible or common: each well's own efficiency, one efficiency per assay over all its plates, an efficiency assumed to be 2.0 (the 2^-ΔΔCq assumption), the plate's dilution series. They are tested only when you ask: **Propose testing the efficiency models** adds a proposal to the inbox of this stage (the engine checks it; models that do not apply to your file are left out, with why). Accept it (or **Edit…** to choose the models with one switch each) and the study is analysed again with the efficiency model as one more choice of the grid: a new card, *which efficiency turns Cq into quantity*, says what each model changes, and the analysis in use stays LinRegPCR's mean efficiency until you decide that card. Your choices on the other cards are carried to that analysis as after leaving a well out (a choice that matters more there is asked again); **Propose to stop testing them** goes back to the analysis without the efficiency models, again with your choices. The choice is recorded in the design, so the Analysis Record re-runs it. A study analysed outside Studio shows the command instead: `qpilot run --efficiency all`.

*On the demo:* the efficiency model alone changes 6 of the 58 calls (each well's own efficiency 5, an assumed 2.0 4, the dilution series 3); one efficiency per assay does not apply (each assay is on one plate).

**Confirm the analysis choices…** appears when every card is decided. It shows exactly what the confirmation covers ("This confirms exactly these:"); **Yes, confirm** fixes the option in use on every card for the Prism export and the record, and opens Prism. Until then Prism is locked ("Decide the analysis choices first").

*On the demo:* ODC1 is called up at 3.59× under the recommended choices; the usual Excel route (2^-ΔΔCq with a t-test on the linear scale) would change 14 of the 58 conclusions.

## 8. Gene

Open a gene from the Results map or table, or from **Go to a gene** (or ⌘K). `[` and `]` go to the previous and next gene. Without a gene in the address, the page lists every compared gene to choose from.

The header gives the gene's name (with a **Headline gene** badge for the study's headline genes), the fold change with its 95 % confidence interval, the p-value, the number of samples per group, the **confidence** level with its reasons, and the **audit verdict** ("Not audited yet" before the audit has run). **Copy summary** puts a plain-text summary of the gene on your clipboard. A row of links under the header jumps to each part below.

* **What holds.** How often the same call comes out when the analysis is done another way, and a strip with every analysis as a dot on the fold-change axis, coloured by call. A switch, **Which analyses**, chooses between *qPilot's grid* (the analyses qPilot checks: every combination of the Decision Cards' options) and *The audit* (the audit's reasonable analyses; shown once the audit has run), each with its own count. A strip spread across the 2× line is a gene whose call depends on your choices.
* **One choice at a time.** For each decision, a dot per option, with every other choice as planned. A ringed dot changes the call on its own.
* **Your samples.** Each sample's normalised value, relative to the mean of the rest, by group. Click a sample to open its well, its plate, its Cq, and badges such as "Leaving it out changes the call", "No Cq: never amplified" and "Flagged by LinRegPCR". An outlier is a place to look, not yet a reason to remove it.
* **What changes it, what it leans on, what to do** (after an audit): the choices that flip it, the samples that change the call on their own, and what to check or fix.
* **Decision Cards that affect this gene**, each marked "Can change the call alone" or "Does not change the call alone".
* **Assay and wells** (efficiency, and after an audit the wells' Cq range and undetermined wells) and **Reference genes** (geNorm stability).

## 9. Audit

The audit re-runs your **confirmed** study under every combination of eight analysis decisions (efficiency model, flagged wells, late Cq, empty wells, which control genes, where to cut the groups, which test, correction for many genes): 90,396 analyses on the demo, about 50 seconds. It first checks that its own baseline reproduces qPilot's results gene by gene; if it does not, it refuses and writes nothing. It then gives each gene one of the six verdicts of [section 3](#3-three-scales-you-will-see-everywhere). A verdict counts only the audit's reasonable set (144 analyses on the demo: no shortcuts such as single or paired control genes, and the group cut-off and the correction for many genes as planned); the rest of the 90,396 are there so that you can see how far a choice would take a result. Those two decisions change the claim rather than the analysis, and are reported separately. The audit changes nothing: it writes its own folder beside the Analysis Record, with a checksum for every file and the decision chain it describes.

* **Not run yet:** the page explains what the audit does and shows what it will cover (analyses, genes compared, samples, sets of reference genes), with **Run the audit** (a job with stages). Running it again keeps the earlier audit.
* **Cannot run:** a design with technical replicates, today, because the audit needs one well per sample and gene, or an install without the Decision Simulator. The page says which, in words.
* **Done:** four tabs, **Study**, **What-if lab**, **How it works** and **Verify**.
  * **Study:** the verdict counts, the map, the calls that one choice changes, how much of the spread each decision explains, reference-gene stability, "fix these first", and the queue of data issues it found (wells, samples, plates); an issue about a choice offers **Try this choice in the What-if lab**.
  * **What-if lab:** one menu per decision, with the options grouped by how defensible they are; every gene is shown from the planned analysis to your chosen one, changed genes first. Nothing is stored and nothing is decided here.
  * **How it works:** the stages with this audit's own numbers, what is varied at each stage, the verdict rules, the known-answer tests and the audit's limits.
  * **Verify:** "Is this audit intact, and is it this study's?": the audit's checksums, whether it reproduces qPilot's result, whether it belongs to this study's record, and whether decisions were made since it ran (then it is not current and the page says to run it again). It lists the audit's files with their SHA-256 (click a name to save one) and the command to check it from a terminal.
* **Audit shown:** if you started `qpilot app --audit DIR` (or `qsim app --results DIR`), a menu switches between this study's audit and the attached results folder, which is shown read-only.

## 10. Prism

For people who finish their figures in GraphPad Prism: "Hand GraphPad Prism numbers it cannot misread, and see what changed when the tables come back." qPilot does not replace Prism and is not affiliated with GraphPad Software or Dotmatics. The section is open once you have confirmed the analysis choices on Results (until then it is locked: "Decide the analysis choices first"), and a row of steps at the top shows where you are.

* **What the usual route into Prism would change** shows how often the usual Excel-to-Prism routes (2^-ΔΔCq with a t-test on the linear scale, the same with Student's test, ΔΔCq at an assumed efficiency of 2.0) would change a conclusion on this study: the same plates, groups and reference genes, taken through the steps most labs use between the instrument and Prism.
* **The Prism project** says which genes get a table, the test, the graph and the caption. It is a proposal like any other: press **Draft the Prism project**, read it ("Why this test" opens the reasons), and accept it; nothing is used until you do. If a decided choice or an accepted exclusion has changed the analysis since, the project you accepted earlier belongs to the earlier analysis and the page asks you to draft it again.
* **What Prism will get** previews the tables of one gene (choose the **Gene**): every biological unit, and the group means with their 95 % confidence intervals as an approximation of what Prism will draw (a nested layout with technical replicates is drawn by Prism itself; the table shows what it gets). It also lists the analysis choices the tables are exported at, and who decided them. Nothing is written until you press **Send to Prism**.
* **Send to Prism** writes a bundle (one table per gene, the Prism scripts, the provenance and a README) into a new folder and offers it zipped to download; the answer gives the folder (with a copy button) and says whether Prism was started: it starts Prism only if Prism is installed ("Prism was not started." otherwise). The script follows GraphPad's documentation but **has not yet been run in a real Prism seat**, and Prism's template files must be made once by hand ([prism.md](prism.md)). **Send again** writes a new bundle.
* **Round trip: what changed in Prism.** In Prism, make your edits (leave a sample out, change a value) and save the projects. Then choose the **bundle sent from this session**, give the **folder Prism sent the tables back to** (a full path inside your home folder or qPilot's export folder, for example `~/Documents/qpilot-prism/sent_back`; links and the study store are refused) and press **Read what came back**. Every value changed, excluded or deleted in Prism comes back as a question, with what accepting it would change, computed by qPilot: for example "ODC1 3.590× → 3.319×, still up; 0 of 58 conclusions change". When several samples are excluded, each card also shows what they do together; one at a time may change nothing while together they change a call. Accepting one re-runs the analysis. A question that is out of date says so and cannot be accepted until you read the folder again. If Prism sent back exactly what qPilot wrote, the page says "No differences".

## 11. Record

**The decision chain**, newest first: every entry has its sequence number, the card and the option, who decided (a person, an agent or the system), the reason, the time, its hash and the previous entry's hash, and its status (applied, waiting, turned down, out of date). Each entry's hash covers the entry before it, so changing any line breaks every later link. A filter ("Show entries by") narrows the list; the chain starts with the input file. Before the study is analysed the section says the record starts when the design and the curves are confirmed.

* **Export the Analysis Record** (**Export again** once you have one) writes one zip: your input file (when it is still on disk), the design, every decision with its reason and actor, the results, and their checksums. The page then shows the record's id and chain head and the file to download, and lists the records exported since qPilot started. If decisions were made after an export, it warns: "Decisions were made after this record was exported; export again to include them."
* **Verify a record** takes a zip (yours, or one you received; it is read on this computer only) and checks that every file matches its checksum, that the files agree with the chain, that the decisions, the cards and the record's summary say the same thing, and, if there is one, that the audit bound to it verifies and belongs to it. The answer is "This record checks out" or "This record does not check out", with what it says about itself.
* The page also gives the commands that repeat the checks outside it: `qpilot verify <record.zip>` (checksums, the decision chain and the proposal chain) and `qpilot rerun <unzipped folder>` (re-analyses the input and compares every result byte for byte).

The chain is **tamper-evident, not tamper-proof**: nothing is signed, so someone who rewrites every hash consistently is not detected unless you compare the record's id with a copy kept elsewhere. qPilot is not a 21 CFR Part 11 system.

## 12. Agents

For agents that work with qPilot over MCP (Claude Code, for example). The section opens with "AI agents work on your studies through qPilot's MCP server. They read, open and propose; a choice that can change a conclusion always waits for a person."

```bash
claude mcp add qpilot -- qpilot serve
```

* **Connect an agent** shows this command with a copy button (it names the study store when `qpilot serve` would otherwise use another one), and the rules qPilot's code enforces whatever an agent or its model says.
* **The tools** are grouped by what they can change: **Read** (studies, genes, the audit and the inbox; they change nothing), **Open** (open a file as a study or a Studio session; they decide nothing), **Propose** (add a proposal to a Studio inbox; only a person accepts, edits or rejects it) and **Request a decision** (ask for a choice on a Decision Card; one that can change a conclusion always waits for a person). Each tool says what it can change.
* **Requests waiting for a person** lists every agent request in every study, oldest first, with the agent's reason. Choose **Approve** or **Turn down** and say why (the same as on Results); one that could change a conclusion is marked as such. The agent bell in the top bar counts them, and a request an agent makes reaches the page within about a second.
* **Recent agent activity**, newest first: the requests and choices agents made on Decision Cards, and the proposals they made in Studio inboxes, for this study or for all; each says what happened ("Waiting for a person", "Answered by a person", "Not applied: the card changed"). For a study whose design and curves are not confirmed yet, requests and entries are counted but not listed.

**What agents may do on their own** is a setting of each study, with the autonomy switch in that study's top bar; a new study starts at **Suggest**. In *Suggest* every request from an agent waits for you. In *Decide and tell me* an agent may apply a choice that cannot change any conclusion, and you are told (the entry is in the record, marked as the agent's, with Undo on its card); everything else still waits for you, at either setting. A choice that can change a conclusion is always yours. Each change of the setting is kept beside the decision chain, with who made it. An agent that can run commands as you can still act as you; give agents MCP access, not your shell.

## 13. Ask

Press ⌘J (or the Ask button in the top bar) and ask the open study a question in plain words; the box says "Ask about a gene, a choice or the study", and **Try one of these** offers questions written from your own study. Until the design and the curves are confirmed the drawer says it waits until the study is unblinded. **Answer from** chooses between the study's own engine and, once the audit has run, the audit's (verdicts, what-if and what-to-check-first questions go to the audit by default).

Every answer says which tool answered it (the study summary, one gene's robustness, the sample-size planner, where a number comes from, a change request on a Decision Card, or an audit look-up), how the question was routed (the model, keyword matching, or fixed reading rules), who wrote the words (the model, with every number checked, or qPilot's checked template), and a table of **the numbers in this answer, from the study's facts**. Text that contains a number the engine did not produce is discarded. **What the model saw** shows the exact last payload this qPilot process sent to a model (kept in memory only; withheld while a design or curves stage is unconfirmed unless it came from the Design Interpreter).

Ask never changes a choice, at either autonomy setting: it only reads. If you ask it to change one, it writes nothing, says "Ask never changes a choice" and names the Decision Card where a person decides it.

## 14. Settings

* **Model.** The provider (none, a local OpenAI-compatible server, or Anthropic) comes from the environment (`QPILOT_MODEL_PROVIDER` and the other variables in [agents.md](agents.md)); the page shows its status and reason, **Check connection**, and **Test this model**, which scores the model on your study (correct answers, invented numbers caught, safety, fallbacks, latency). The page has no field for an endpoint or a key, on purpose.
* **What agents may do on their own** explains the two levels and shows the policy lines; it sets nothing. The setting belongs to each study and is changed with the autonomy switch in that study's top bar ([section 12](#12-agents)); a new study starts at *Suggest*.
* **Theme** (system, light or dark; saved in this browser).
* **Start a fresh demo…** asks first, then moves the demo's earlier work aside to a kept folder (`studies-archive/`, next to the studies folder; never deleted) so you can walk it again from the start. Your own studies are not touched.
* **What qPilot never does**, and **This install**: the version, the curve method and its commit, whether the audit is installed, the Python version and the studies folder (with a copy button).

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

## 18. What this study cannot tell you

On Results, the **Evidence Ledger** lists what your data has and lacks: NTCs on every plate,
no-RT controls, reference candidates with geNorm M and V, where the efficiency comes from, whether
the curves are raw, RNA integrity, RT replicates, biological units, an inter-run calibrator,
reagent lots, instrument and calibration dates. Each item is **present**, **absent**, **unknown**
or **not applicable**, and says what that means for your conclusions; the absent and unknown ones
come first. An absent item never changes a conclusion or a confidence level: it says what this
study cannot show (for example, without a no-RT control, genomic DNA carry-over cannot be
checked). When you opened an instrument export, the raw-ness item reads qPilot's own check of the
curves; for an RDML file it says the file did not go through that check.

*On the demo:* 3 items present, 6 absent, 1 unknown, 1 not applicable (no no-RT control, no RNA
integrity, no RT replicates, no sample sheet naming biological units, no lots, no instrument dates).

## 19. Where to look

In **Trace**, **Where to look** follows a gene's result, one sample or one well (`PLATE:WELL`)
back through the normaliser and the reference wells to the plate controls, and lists the places
to look first: the sample, plate and well, what is unusual there (for example "one reference well
disagrees with the sample's other reference wells"), what to check, and what each option would
do: keep it, read that well from the sample's other reference wells, or set the sample aside. A
place where an option **changes a call** has **Decide…**: it opens that place as a Decision Card
on Results, where you decide it with a reason like any other card. Deciding it is your choice,
kept in the record; the study's numbers stay as analysed (to leave a well out of the analysis,
leave it out in Curves or from Controls). An agent can ask, never decide such a card.

Where to look traces the analysis in use (your decisions applied). *On the demo:* CAMTA2 (no call)
points first at tumour 2016, plate HMBS_20080318, well K22: that HMBS well reads Cq 46.1 while the
tumour's four other reference wells agree, so all 58 of its values read 5.55× too high; reading
the well from the other four makes CAMTA2 down.

## 20. Run Review and the Excel workbook

In **Report**, the **Run Review** is one page for the person who reviews someone else's run: the
headline genes, what the study cannot tell you, and every sign-off so far. Sign off with
**Accept**, **Repeat** or **Discuss**, a comment and your name: it goes into the decision record as
yours, changes no result and no card, and qPilot never passes or fails a run for you. If something
was decided while you were reading, the review is shown again and you sign off on what is there
now.

Report's exports include an **Excel workbook**: the results table with a "Trace" column naming
each gene's first place to look, a "Where to look" sheet and an "About" sheet. It shows the
results at the recommended choices, as the Analysis Record does.

## 21. Sheet check

**Sheet check** (under *Lab* in the rail) recomputes your own ΔΔCq spreadsheet (`.xlsx` or
`.csv`) from its own Cq values: how many fold changes reproduce, the first column and row that
differ, and the known slip that reproduces it (an inverted sign, the exponent applied twice,
statistics run on fold changes, …). Compared with a study, genes whose arithmetic reproduces but
whose fold change differs from qPilot's are a difference of method, not a slip. qPilot guesses
which column holds what and says so until you **confirm the mapping** (change any column first).
Your sheet is never edited, nothing is saved, and its sample and group names are not shown back.

## 22. Instruments

**Instruments** (under *Lab*) is your lab's working memory for each instrument: its latest
calibrations and their age, open incidents, and its logbook (a hash chain, so an edit shows).
An agent may only propose an incident; you **confirm** it or **turn it down** here, and note what
fixed it. Log calibrations, part changes, service visits, moves and notes yourself. **Read a run
file** (`.eds`, a QuantStudio or CFX export, RDML) shows what the file says about the instrument
and the run (calibration dates, pauses, an aborted run); serial numbers never leave your
computer, and the first file from an unknown instrument asks once which instrument it is.
**Lookback** answers "which of my conclusions used this instrument between these dates, and what
changes without those runs?"; it writes nothing.

## 23. RT replicates and run files on Controls

Two of the rules on **Controls** look past the control wells.

* **G-RT** (reverse-transcription replicates): when your sample sheet's `rt_replicate` column
  marks samples of one biological unit that were reverse-transcribed separately from the same
  RNA, each unit and gene gets a verdict. The Cq of each RT replicate is the mean of its wells; a
  range of one cycle or more between them is a warning (the criterion as quoted from Bustin et al.
  2015, still to be checked against the paper). Like every warning, it is priced: qPilot re-runs
  the analysis without that unit's wells for that gene and says whether a call changes. Without
  RT replicates in the sheet the rule says the spread of reverse transcription is not measured.
* **G-INSTR** (what the run file says): for each plate, whether the run completed, whether it
  was paused or the lid or drawer opened (and in which cycles), which calibrations were past the
  vendor's expiry, and whether a hold drifted from its setpoint. Each is a warning to weigh, not
  a reason to set the run aside: qPilot re-runs the analysis without the run's study wells and
  says whether a call changes. An RDML file names the instrument and the run date at most, so
  link the run file your instrument wrote (an `.eds`, a QuantStudio results export or CFX run
  information) to its plate on the **Run files** card, or from the plate's G-INSTR check. The
  link is kept for every analysis of the file, with when you made it; **Unlink** removes it.
  Linking changes no number, and serial numbers never leave your computer.
  If you opened your instrument's export instead of RDML and it carries the run's own record (a
  QuantStudio results export, which starts with the run's header, or CFX's Run Information sheet
  exported with the data), G-INSTR reads it for its plate without a link and says it read "this
  plate's run file in the instrument export". A run file you link still comes first.

*On the demo:* no RT replicates are marked and the file is RDML, so both rules are not
applicable (one line for G-RT, one per plate for G-INSTR), each saying what would let it check.
