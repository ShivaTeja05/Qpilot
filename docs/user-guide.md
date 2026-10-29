# qPilot: a scientist's guide to the page

qPilot reads your qPCR instrument's raw amplification curves, analyses every plate the same way, and shows you which of your analysis choices could change a conclusion. **The AI proposes. The engine checks. You decide.** This guide walks through the page section by section: what to look at, what each word on it means, and what to do next. For research use only; not for clinical or diagnostic use.

The page runs on your computer. It sends nothing anywhere unless you press a button that says so (downloading the demo study, or asking a model you configured). Everything below was checked against the demo study, 64 plates of neuroblastoma tumours (Vermeulen et al. 2009; raw curves from Ruijter et al. 2013), and against real files labs published (the [corpus](conformance.md)); the numbers quoted come from running qPilot on them. No language model is needed for any of it.

## How do I …

| … | Go to |
|---|---|
| install qPilot | [install.md](install.md) |
| open my own file (RDML, an instrument export, my Excel Cq table) | [4. Open](#4-open) |
| analyse a table of Cq values when I have no curves | [4. Open](#4-open), [cq-tables.md](cq-tables.md) |
| say which genes are references and which samples are in which group, with no model | [6. Set the design yourself](#6-set-the-design-yourself) |
| compare more than two groups, or paired samples | [9. Comparisons](#9-comparisons) |
| get copies per reaction from my standard curve | [10. Quantities](#10-quantities) |
| quantify samples with no groups to compare (a viral load, wastewater, a library) | [6. Set the design yourself](#6-set-the-design-yourself), [10. Quantities](#10-quantities) |
| work with a multiplex plate (several dyes per well) | [7. Curves](#7-curves-blind), [11. Controls](#11-controls-the-run-gate-and-melt-curves), [multiplex.md](multiplex.md) |
| check my controls and melt curves | [11. Controls](#11-controls-the-run-gate-and-melt-curves) |
| decide the choices that could change a conclusion | [8. Results](#8-results) |
| find the well behind a surprising result, and leave it out | [14. Trace](#14-trace-where-to-look) |
| check a sentence of my paper against the numbers | [15. Claims](#15-claims) |
| get my numbers, figures, Methods or a supplement for a journal | [17. Report](#17-report-methods-miqe-the-run-review-and-exports) |
| know what to repeat on the next plate | [17. Report](#17-report-methods-miqe-the-run-review-and-exports), [18. Plan next](#18-plan-next) |
| finish my figures in GraphPad Prism | [19. Prism](#19-prism) |
| share a record anyone can re-run | [20. Record](#20-record) |
| let an AI agent help, safely | [21. Agents](#21-agents) |

## Contents

1. [Start the page](#1-start-the-page)
2. [How the page is laid out](#2-how-the-page-is-laid-out)
3. [Three scales you will see everywhere](#3-three-scales-you-will-see-everywhere): call, level, verdict
4. [Open](#4-open)
5. [Design (blind)](#5-design-blind)
6. [Set the design yourself](#6-set-the-design-yourself)
7. [Curves (blind)](#7-curves-blind)
8. [Results](#8-results)
9. [Comparisons](#9-comparisons)
10. [Quantities](#10-quantities)
11. [Controls: the Run Gate and melt curves](#11-controls-the-run-gate-and-melt-curves)
12. [Gene](#12-gene)
13. [Audit](#13-audit)
14. [Trace: where to look](#14-trace-where-to-look)
15. [Claims](#15-claims)
16. [History](#16-history)
17. [Report: Methods, MIQE, the Run Review and exports](#17-report-methods-miqe-the-run-review-and-exports)
18. [Plan next](#18-plan-next)
19. [Prism](#19-prism)
20. [Record](#20-record)
21. [Agents](#21-agents)
22. [Ask](#22-ask)
23. [Sheet check](#23-sheet-check)
24. [Instruments](#24-instruments)
25. [Settings](#25-settings)
26. [Keyboard](#26-keyboard)
27. [When something does not work](#27-when-something-does-not-work)
28. [What the page never does](#28-what-the-page-never-does)

## 1. Start the page

Not installed yet? See [install.md](install.md) (Windows, macOS or Linux; one line with pipx or uv).

```bash
qpilot app
```

qPilot prints a link that starts with `http://127.0.0.1:` and opens it in your browser. **Use that link:** it carries a key that belongs to this launch, which is what lets your browser, and nobody else, use the page. Another program, another user of this computer, or a web page in your browser cannot use the page without it. If you close the tab, open the link again from the terminal. Stop qPilot with Ctrl-C in that terminal.

* The page is on port 7860, or the next free one (`--port N` chooses). It answers only on `127.0.0.1` / `localhost`.
* Right after qPilot starts, the bell shows "Getting ready", then "Preparing what the page shows next" for a minute or so. You can work meanwhile; the sections it prepared open in under a second.
* Your work is kept in the study store (`~/.cache/qpilot/studies`, or the folder in `QPILOT_STUDIES_DIR`), the same store `qpilot serve` (agents) uses, so a decision made by an agent shows up on the page within about a second. The store is in a cache folder by default: set `QPILOT_STUDIES_DIR` to a folder you back up ([install.md](install.md#5-where-your-data-lives)).
* `qpilot app --fresh-demo` moves earlier demo work aside (kept, never deleted) and starts the demo clean.
* A second `qpilot app` has its own key. If you open both in one browser, the newest link replaces the earlier launch's key and the earlier tab asks you to open its link again.

## 2. How the page is laid out

* **The rail (left).** The workflow in order: **Design → Curves → Results → Controls → Audit → Prism → Record**, then the tools (**Trace**, **Claims**, **History**, **Report**, **Plan next**), **Agents**, and the lab sections (**Sheet check**, **Instruments**, **Settings**). Each workflow step shows where it stands: a check when it is confirmed (for the Audit: when it has been run), a count of the proposals or requests waiting for you, or a lock with the reason in words, for example "Confirm the design first" or "Blind until the design and the curves are confirmed". At the top, the workspace switcher lists your recent studies (⌘O opens a file). On a narrow window the rail shrinks to icons, and on a phone it becomes a bar at the bottom.
* **The top bar.** The study's title and, on a wide window, the start of its input file's SHA-256 (click to copy). The **chain pill** (`chain 3f2a…`, or `chain empty` before any decision) shows the head of the decision chain; click it to open the Record. The **model chip** says `no model`, `local <name>` or `REMOTE — names pseudonymised`, with a dot for whether the model is answering. The **autonomy switch** (Suggest · Decide and tell me) sets what agents that connect over MCP may do on their own in *this study* ([Agents](#21-agents)). The **agent bell** (requests waiting for you, and work that is running or being prepared). **Ask your data** (⌘J). **Go to…** (⌘K, the command palette). The theme toggle (system, light, dark). The **live dot**: green means the page is connected to qPilot and changes made by an agent or another tab appear within a second.
* **⌘K** opens the palette: go to a section, a gene or a study, or run an action such as **Propose the design**, **Confirm this stage**, **Check the curves**, **Run the audit**, **Send to Prism** or **Export the Analysis Record**. Actions that are not reachable yet are not offered.
* **The next-step banner** under the top bar says what to do next in this workspace ("Next: Decide 3 analysis choices"), with a button that goes there.
* **Slow work** (checking curves, running the audit) appears as a card that says what qPilot is doing, how long it has taken and how long it usually takes. You can move to another section; it keeps running, and the bell lists it.
* **Every change you make** brings a short message saying what happened, with **Undo** where the record allows it.

A *workspace* is one study at a time. Opening a file creates a **Studio session** (the sections Design, Curves, Results, … in that order). A study that was analysed outside the page (by `qpilot run`, or by an agent) is also a workspace; it has no Design or Curves, and its Results show straight away.

## 3. Three scales you will see everywhere

**A call** is what the analysis concludes about a gene: **▲ up**, **▼ down** or **— no call**. The rule is fixed and printed on the Results page: a gene is called up or down only if p < 0.05 **and** the change is at least 2-fold. A gene that does not meet both is "no change called", which is not the same as "no change". With several comparisons, p is the Holm-corrected p of that comparison ([section 9](#9-comparisons)).

**A level** says how far to trust one gene's result: **High**, **Moderate**, **Low**, **Very low** (four bars, three, two, one). It is never a percentage. A gene starts at High and moves down one level for each of three checks it fails:

* *precision*: its 95 % confidence interval crosses the 2-fold line;
* *robustness*: its call holds in fewer than 80 % of the analyses qPilot checks (qPilot's choice grid, below);
* *normalisation*: fewer than two control genes are stable by geNorm (M below 1.5), or no V(n/n+1) is below 0.15.

It moves up one level only when the change is at least 4-fold (or at most a quarter), the call holds in every analysis qPilot checks, and the precision and normalisation checks pass. A level can also be capped, with the reason named (for example "vendor-baselined curves", [section 8](#8-results)). The reasons are always listed beside the level, in words. Three more facts are reported but do not change the level: how few choices at once flip the call, the assay's efficiency and undetermined wells, and the smallest change your design could detect.

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

* **qPilot's choice grid** (Results, Gene, Ask, the Decision Cards): "holds in 65 % of the 744 analyses qPilot checks". It is every combination of the options on the Decision Cards: every control-gene set (single genes included), group cut-off, rule for empty wells and rule for which curves count as amplified (31 × 3 × 2 × 4 = 744 on the demo), plus the efficiency models, normalisers or corrections between plates when you ask qPilot to test them. It sets each gene's confidence level.
* **The audit's reasonable set** (Audit, verdicts, the gene card): "same call in 144 of 144 of the audit's reasonable analyses". The robustness audit is a wider, independent re-analysis that varies eight analysis decisions, nine with technical replicates; its verdicts leave out shortcuts such as single or paired control genes, and hold the group cut-off and the correction for many genes as planned. The audit also runs its full grid (90,396 analyses on the demo) so you can see how far a choice would take a result.

The two answer different questions, so they differ: on the demo NM23A's call holds in 65 % of qPilot's 744 analyses and in all 144 of the audit's reasonable set. **Why two counts?** (on the Audit and Report pages) says, for your study, which decisions only the audit varies. On the Gene page both counts appear, each labelled.

## 4. Open

The first screen. It says what qPilot does in four steps (the AI proposes; the engine checks; you decide; the record keeps it) and offers three things:

* **Open your file.** Drop it on the box, or press **Choose a file…** (⌘O does the same anywhere). qPilot takes:
  * **an RDML file** (`.rdml`, `.xml`, or a zipped file such as a LightCycler 96 `.lc96p`; RDML 1.0 to 1.4), the instrument-neutral format most qPCR software can write;
  * **what your instrument exported**: one file or a whole export set (up to 64 files) from Bio-Rad CFX Manager / Maestro, QuantStudio / StepOne / 7500, LightCycler 480 (raw-data text or a Cp table), or a tidy table. qPilot reads the files by their content, not their names, writes them once into RDML, and names back what it cannot take (a vendor project file such as `.eds` or `.pcrd` says how to export it);
  * **your own Excel Cq table** (columns such as Sample, Gene, Condition, Gene Type, Cq), alone or next to the run file: qPilot uses its sample columns as the sample sheet (the Condition column gives the groups, the Gene Type column proposes the reference genes) and never shows its numbers before you confirm the design and the curves. A Cq table, or an RDML file without curves, is analysed from its Cq values: each assay's efficiency comes from its dilution series on the plate, else is assumed to be 2.0, and confidence is capped (Low while an efficiency is assumed, Moderate otherwise) because no curve could be checked. Curves are better when you can export them: [cq-tables.md](cq-tables.md).

  You may add a **sample sheet** (`.xlsx` or `.csv`) and **one sentence about the experiment**, for example "LPS versus PBS, three mice each" (at most 500 characters; the rules and a model read it when they propose the design, and it is never obeyed as an instruction). Then press **Open this file**. Opening reads the file and quarantines every name in it; it analyses nothing and proposes nothing yet, and the file stays on this computer. Which files from which instruments open, and what qPilot reads from each, is listed in [conformance.md](conformance.md).
* **Open the demo study.** A public neuroblastoma study (Vermeulen et al. 2009; raw curves from Ruijter et al. 2013), to see every step on real data before you open your own. The card shows the study, its licence and its SHA-256. If the file is not on your computer yet, the button reads **Download 7.0 MB and open**, and the card says where it comes from (the RDML consortium's repository, at a pinned commit, checked against its SHA-256 before it is used). That is the only thing this screen downloads, and only when you click. Once the demo has been opened the card says **Continue the demo study**; to start again from a clean study, use **Start a fresh demo** in Settings.
* **Recent.** Your earlier workspaces, the most recently changed first, with a filter box. Each card shows the title, the file, plates · samples · genes, a chip for each stage, the number of decisions recorded, when it was last changed, and badges: **Demo**, **Audited**, **Analysed outside Studio**, the number of agent requests waiting for you, and **File missing or changed** when the original file is no longer where it was.

At the bottom: the qPilot version, the model chip, the vendored curve method and its commit, the line that says what can leave this machine (the same as `qpilot doctor`), and whether the robustness audit is installed.

## 5. Design (blind)

*Blind* means that until you have confirmed the design **and** the curves, the page shows nothing that pairs a group with a number: no fold change, no p-value, no direction of change. The server refuses to send it. This keeps your choices of groups and controls from being steered by the result you hope for. The header of this screen says "Blind stage 1 of 2".

**What to do.** Press **Propose the design** (about 9 seconds on the demo). qPilot's rules, and a language model when one is configured, read your file, your sheet and your sentence and propose how to read the plates: which samples are standards, controls or study samples (and what each control is), which are in which group, which samples are the same biological unit, which genes are references, which gene each target is, which groups to compare. **Propose the design again** reads the file again: new proposals join the inbox, what you already decided stays decided, and a repeat of a decided proposal is refused. Whatever the rules cannot read from your file, you set yourself ([section 6](#6-set-the-design-yourself)).

**When the file was an instrument export**, the **Imported from …** card says what was read (files by their names, plates, wells, cycles, targets, dyes, declared sample types, the instrument's own Cq and omitted wells) and whether the curves look raw, normalised to a passive reference, or baseline-subtracted before export. Baseline-subtracted (or unknown) curves are analysed with every gene's confidence capped at Moderate until you decide the **Import Trust** card on Results ([section 8](#8-results)).

**The inbox** lists one card per proposal, the ones the engine **contradicts** first. Filter it by engine check (all waiting, consistent, contradicted, cannot check) or by kind of proposal, or find a sample or target by name. **The plate map** shows each plate's wells coloured by their declared type (**View as table** gives the same as text); click a well for the names in it, quoted from your file, and the proposals about it. A name that reads like an instruction is marked and never obeyed.

**A proposal card** shows the proposal in words and the other readings that were considered, then four parts you can open:

1. **Why**: each piece of evidence: the text from your file with where it came from, a cell of your sheet, or a well (which opens its curve).
2. **Engine check**: **Consistent** (the engine found nothing that refutes it; a check can refute, never prove), **Contradicted** (it refutes it, with the rule and the numbers), or **Cannot check** (decide it on the evidence).
3. **Consequence**: hidden in the blind stages, except "This matters for at least one conclusion; decide on the evidence." On a design proposal that has another reading, **Does this matter?** has the engine run the design both ways: it answers only "this matters" or "neither reading changes any conclusion".
4. **Level**: an ordinal level with its reasons (never a percentage).

Then **Accept**, **Edit** (change the fields; the engine checks the edit, then you accept it) or **Reject** (a reason is required). If the engine contradicts a proposal the button reads **Accept anyway…** and asks you to say why. The footer says who made the proposal: a fixed rule, a model (with its name and prompt hash), an agent, or you.

**Many at once.** **Accept all consistent…** shows the exact list first; **Accept these N** accepts exactly that list, one record entry each. A contradicted or cannot-check proposal is never on it. **Reject contradicted AI calls…** does the same for model and agent proposals the engine contradicts, with one reason you type.

**Confirm this stage…** is offered when every proposal is decided and the design has what it needs (at least one reference gene, two groups and a comparison; the card above the editor says what is missing). It shows exactly what the confirmation covers. **Yes, confirm** confirms. A later decision on a design proposal re-opens the stage.

*On the demo:* the rules make 131 proposals; 121 are consistent and 9 are contradicted (seven competimer standards that never amplified, one competimer series, and one standard series whose R² is only 0.694). Reject those nine with a reason, accept the rest, confirm.

## 6. Set the design yourself

No model? Use **Set the design on this page** on the Design screen. You choose what each target and sample is; the engine checks every choice; each change is recorded as your decision, with your reason. Nothing changes until you record it. Details: [design-editor.md](design-editor.md).

* **What is this study for?** **Compare groups** (the default) or **Quantify samples**, when the run only measures how much is there (a viral load, a wastewater sample, a construct's copy number, a library). A quantification needs standards with their quantities (at least three levels), not a reference gene, groups or a comparison; *What the design still needs* asks for those instead. Groups you set then only sort and label the samples, and a comparison set earlier is kept aside and comes back if you switch back. The rules propose *Quantify samples* when the file declares the standards' quantities and no sheet names groups; it is never in "Accept all consistent".
* **How do I mark the reference genes?** Open **Targets** and give each target a role: **Reference gene** (a housekeeping gene the others are normalised to), **Gene of interest**, or **Leave out** (an empty channel, a spike-in, an assay not part of this experiment; none of its wells is used). Some instruments (the LightCycler 96, for one) declare every target a reference gene; the page says so, and you choose.
* **How do I put samples in groups?** Open **Samples** and select samples: click one, Shift-click a range, ⌘/Ctrl-A for all, type a name pattern such as `KO*` and **Select matching**, or click wells on the plate map (Shift-click a rectangle, a row letter or column number for a whole row or column). Then type the **Group** and press **Put in group**. Wells of one sample are its technical replicates.
* **How do I say which samples are the same animal or donor?** Select them and press **One biological unit** (or **Each its own unit**). Samples of one biological unit are averaged and count once.
* **How do I mark controls and standards?** Select them and choose a **Sample type** (study sample, standard, NTC, no-RT, no-amplification, positive control, no-target-present, calibrator). For **Standard**, give the highest quantity and the dilution step; the quantities follow in plate order. **From ng to copies…** works the highest quantity out from a mass and the amplicon's length (dsDNA, ssDNA or RNA).
* **How do I paste my sample list?** Open **Paste a list** and paste two columns copied from Excel (sample, group; a third column is the biological unit). The names are matched to the file's.
* **How do I choose what is compared?** Open **Comparison**. **One comparison**: choose the compared group and the reference group (the baseline the fold change is relative to). **Several comparisons** (three or more groups): each group against a control, every pair of groups, or your own list, and the correction; see [section 9](#9-comparisons).
* **What names can I use?** Your own: a group, unit or gene name may use any letters, digits, spaces and signs (`LPS + inhibitor`, `IL-6/ctrl`, `Day 3 (50 µM)`, `α-syn`), at most 64 characters, and keeps it in every table, figure, report and export. For the Prism project a group or unit cannot start with `=`, `+` or `@` (Prism would read it as a formula).
* **Can I fill in a sheet instead?** **Sample sheet** downloads a template pre-filled with this plate's sample and target names; fill it in Excel and attach it to this session (no need to open the files again). A target-role column (Gene Type, Reference, Housekeeping, …) is read too. The rules then propose from it.

Changes collect in a draft ("3 changes not recorded yet"). **Review and record…** shows, before anything is written, what each change does and the engine's check of it, which waiting proposals it settles, and what is refused. One reason covers the act and is kept with every item. A waiting proposal that says what you set is accepted (so who proposed it stays on record); one that says something else is rejected with your reason. A declared control (NTC, no-RT, no-amplification) never gets another type or a group: such a change is refused in words and nothing is written. A whole 96-well plate records in about a second.

## 7. Curves (blind)

Opens when the design is confirmed (until then it is locked: "Confirm the design first"). Press **Check the curves** (about 15 seconds on the demo; afterwards it reads **Check the curves again**). qPilot fits every curve with LinRegPCR and a second, learned reader (the *Curve Judge*) classifies each as amplified or not. Wherever the two disagree **and it could change a conclusion**, you get a proposal card (a well call), and a card for the call rule you want to use. Accept, edit or reject them exactly as in Design, then confirm the stage.

* **The curves stage** card says which rule is in use ("LinRegPCR's call (the engine's default), until you accept a rule"), how many proposals you have accepted, rejected and have waiting; **Open the curve** takes you to the well a proposal is about. Curve Judge calls that LinRegPCR refutes are folded together.
* **The plate** shows every well of one plate. Choose the **Gene** and the **Plate** (`[` and `]` step through the plates), and colour the wells by *Amplification call*, *Cq*, *Efficiency*, *R²* or *Sample type*. Pick one well, or several (⌘/Ctrl-click or Shift-click).
* **The curve** shows the raw fluorescence by cycle of the wells you picked, with a linear/log switch, and for one well its Cq, efficiency, R² and baseline and how it is called under each amplification rule.
* **Melt curve** (files with melt curves, such as SYBR Green assays): the −dF/dT of the wells you picked, each peak's Tm, and per assay where its product melts (the Tm the file declares, else the median of its study wells) with the wells the Run Gate's G-MELT rule points at ([section 11](#11-controls-the-run-gate-and-melt-curves)). A single peak at the expected temperature does not guarantee that it is the intended amplicon.

**A multiplex plate** (several dyes per well, such as a gene in FAM and its reference in HEX, or an internal positive control) shows a **Target** picker on the plate: pick a gene to see its curves. Each dye is analysed on its own, with its own baseline, efficiency, Cq and N0; a gene is normalised to the reference measured in the same well. Leaving a multiplex well out leaves out all its curves, so each gene keeps the reference measured beside it. The Curve Judge does not run on multiplex plates. Details: [multiplex.md](multiplex.md).

**A file without curves** (a Cq table) has nothing to fit: **Check the curves** proposes the amplification rule ("a well counts when the file gives it a Cq"), and **Your Cq table** shows each sample's Cq per well and plate, the wells without a Cq, the replicate sets wider than G-REP expects and each assay's efficiency, for you to confirm instead of curves.

There is no group, fold change or p-value anywhere on this screen.

*On the demo:* the Curve Judge disagrees with LinRegPCR on 166 study wells; only 110 early curves of one reference gene (ALUsq) could change a conclusion, and LinRegPCR contradicts each of them with a complete fit. Reject them with one reason, keep LinRegPCR's call rule, confirm. The learned reader is validated only on the demo's instrument (LightCycler 480, SYBR Green I); on another file it is a second opinion at most.

## 8. Results

Opens once the design and the curves are confirmed; qPilot then analyses your confirmed design (about 30 seconds on the demo).

**The summary strip:** plates, reactions, samples, the groups and how many biological units each has, genes compared, calls under the rule (how many up, down, no call), the reference genes with their geNorm stability, and whether the robustness audit has run ("Audited at the current decisions", or "Decisions changed since the audit: run it again"). With several comparisons, **Comparison shown** picks which one the map, the table and the flip matrix show ([section 9](#9-comparisons)).

**The robustness map.** One point per gene. Left–right: fold change (log scale, labelled in ×). Up–down: the share of the analyses qPilot checks that give the same call. The 2× lines mark the rule. A gene far from the lines and high on the map does not depend on your choices; a gene near a line, or low, does. Colour the genes by the call, the confidence level or, after an audit, the audit verdict. Hover or use the arrow keys to read a gene; click it, or press Enter, to open it. **View as table** gives the same numbers as text.

**All genes** is a table you can sort and filter: find a gene by name, and filter by call, by confidence, by audit verdict, or to **only genes one choice can flip**. Each row gives the gene, its call, the fold change with its 95 % confidence interval, p, the share of the analyses qPilot checks with the same call, the confidence level and why. A gene never detected in one group is listed as "detected only in ⟨group⟩" with that group's ΔCq, never as a fold change made from capped values.

**What one choice alone can flip** is the flip matrix: each row is a decision on a Decision Card, each column a gene; a darker cell means more of that decision's other options change the gene's call. Decide those cards before you report the genes they flip.

**Decision Cards** (the right-hand column). One card per choice that could change a conclusion, ranked by how many conclusions it can change: *which control genes*, *where to cut the groups*, *what to do with empty wells*, *which curves count as amplified*, and any further choice you asked qPilot to test (below). Each card shows the question, the evidence and each option with what it changes for the headline genes; one option is marked **Recommended**, and an option that is not advisable (for example a single control gene) is marked **Not recommended (MIQE)**. Choose an option, write a reason (required, at most 500 characters; it goes into the Analysis Record), and press **Decide: <option>**.

* A card where **no option changes any conclusion** is decided automatically, with the recommended option, and shows **Decided automatically**; you can reopen it.
* A choice that **can** flip a conclusion is yours alone: an agent, a model or the system can only ask. An agent's request waits on the card as **Agent request**; give a reason and press **Approve: <option>** or **Turn down**.
* A decided card shows who decided ("Decided by you") and why. **Undo: back to <option>** needs a reason and adds a new entry to the record (nothing is erased).
* **Leaving a well out after the curves are confirmed** (from Trace, Controls, Prism or the Curves inbox), or putting it back, analyses the file again. Your choices on the cards come with you: each is written into the new analysis as a new entry that names the earlier analysis and your entry there, and the card shows **Carried**. A choice that matters more in the new analysis is not carried: its card says what you chose before and asks again. Confirm the analysis choices again; it is one click when every card is decided.
* **Explain with the model** (only when a model is configured) writes a plain explanation whose every number is a fact qPilot computed and cites.
* `j` and `k` move between cards, `Enter` puts the cursor in the reason, and ⌘Enter (Ctrl Enter) decides.

**Import Trust** (first among the cards, only for a session opened from an instrument export whose curves were most likely baseline-subtracted before export, or whose processing qPilot could not tell). Until you decide it, every gene's confidence is capped at Moderate ("vendor-baselined curves"). The options: **Re-export the raw curves** (recommended; the card gives the vendor's recipe, e.g. CFX "No Baseline Subtraction"; this analysis stays as it is), **Analyse the curves as they are** (capped at Moderate), or **Use the instrument's Cq values only** (the curves are not used; quantity 2^-Cq with every cycle assumed to double; capped at Low). Curves normalised to a passive reference (Rn) get no card.

**Reference genes.** The reference-gene panel shows geNorm's M and pairwise V, and **geNorm and NormFinder side by side**: each candidate's stability under both methods (lower is steadier), whether they agree on the best pair, and the units NormFinder left out, with why. Which reference genes the analysis divides by stays your choice, on the reference-gene card; this panel only compares the two rankings. *On the demo* both agree on ALUsq(Eurogentec) and HPRT1.

**Also test …** (under the cards). Some analysis choices are tested only when you ask, each with a panel that says what is in use now:

* **Also test efficiency models**: which efficiency turns each Cq into a quantity. qPilot uses LinRegPCR's mean efficiency of each assay on each plate; each well's own efficiency, one efficiency per assay over all its plates, an assumed 2.0 (the 2^-ΔΔCq assumption) and the plate's dilution series are the alternatives. *On the demo* the efficiency model alone changes 6 of the 58 calls.
* **Also test other normalisers**: what each gene is divided by: the reference genes chosen for this study, NormFinder's best pair, geNorm's best pair, or the mean of every gene measured (the global mean, offered from 50 genes). *On the demo* NormFinder's pair changes 3 of 58 calls and the global mean 19 (the demo's genes were chosen for this comparison, which the global mean assumes they were not).
* **Also test corrections between plates**: an inter-run calibrator (the same calibrator sample on every plate) or a factor correction from the measurements plates share (Ruijter et al. 2015). It matters only when a gene's samples are on more than one plate; it gets a card only when a correction changes a call.

Each works the same way: **Propose testing …** adds a proposal to this stage (the engine checks it; options that do not apply to your file are left out, with why). Accept it (or **Edit…** to choose the options) and the study is analysed again with the choice as one more dimension of the grid: a new card says what each option changes, and the analysis in use stays as it was until you decide that card. **Propose to stop testing them** goes back. Your choices on the other cards are carried. The request is recorded in the design, so the Analysis Record re-runs it. A study analysed outside Studio shows the command instead (`qpilot run --efficiency all`, `--normaliser all`, `--interrun all`).

**Quantities** appears when your plate has standards with known quantities ([section 10](#10-quantities)).

**What this study cannot tell you** (the Evidence Ledger) lists what your data has and lacks: NTCs on every plate, no-RT controls, reference candidates with geNorm M and V, where the efficiency comes from, whether the curves are raw, RNA integrity, RT replicates, biological units, an inter-run calibrator, reagent lots, instrument and calibration dates. Each item is **present**, **absent**, **unknown** or **not applicable**, and says what that means for your conclusions; the absent and unknown ones come first. An absent item never changes a conclusion or a confidence level: it says what this study cannot show (for example, without a no-RT control, genomic DNA carry-over cannot be checked). *On the demo:* 3 items present, 6 absent, 1 unknown, 1 not applicable.

**Confirm the analysis choices…** appears when every card is decided. It shows exactly what the confirmation covers; **Yes, confirm** fixes the option in use on every card for the Prism export and the record, and opens Prism.

*On the demo:* ODC1 is called up at 3.59× under the recommended choices; the usual Excel route (2^-ΔΔCq with a t-test on the linear scale) would change 14 of the 58 conclusions.

## 9. Comparisons

A study can compare more than two groups. **How do I set it up?** On **Design → Set the design on this page → Comparison**, choose **Several comparisons**, then which ones:

* **Each group against a control** (choose the control group),
* **Every pair of groups**, or
* **My own list** (each pair of groups at most once).

Then choose the **correction for comparing each gene several times**:

* **Holm** (any pattern): each gene's p-values are corrected across its comparisons; each comparison keeps its own Welch's t-test (no equal-spread assumption).
* **Dunnett** (each group against a control) and **Tukey** (every pair): one t-test with the spread pooled over every group, corrected for the comparisons made. Both assume equal spread on the log2 scale, and neither is offered with a pairing.
* **No correction.**

When you propose the design, the rules may propose such a plan themselves (each group against a group whose name says it is the control, otherwise every pair, Holm-corrected); accept, edit or reject it like any proposal. A column of your sample sheet that names a donor, an animal or a passage proposes **pairings**, and the plan then uses a paired t-test within each pair.

How the numbers work:

* The call uses the corrected p: "corrected p < 0.05 and at least 2-fold". The page shows both p and the corrected p.
* **q-values** (Benjamini–Hochberg) across genes are shown for each comparison, for reference; they do not change a call.
* With three or more groups, **Welch's one-way ANOVA** is shown per gene, for orientation only: it never makes a call.
* A sample missing one gene is dropped from that gene only.
* **A Decision Card counts a changed call in every comparison.** A choice that changes a call only in a later comparison still waits for you; the card names the comparison and shows each option's effect per comparison. Your choice applies to the whole study.

**Where it shows.** On Results, **Comparison shown** picks the comparison the map, the table and the flip matrix show, and **All comparisons** lists each gene in every comparison side by side. The comparison you pick is followed in Trace (with the corrected call), on a gene's page (its figure draws every group, with a bracket per comparison) and in History; the Run Review names each comparison. The Methods paragraph, the exports (one table per comparison), the MCP tools `qpcr_comparisons` and `qpcr_trace`, and the Analysis Record (`grid_comparisons.csv`) carry every comparison. The robustness audit audits the first comparison and says so ([section 13](#13-audit)). A study with one comparison looks exactly as before. Method card: [methods/comparisons.md](../methods/comparisons.md).

## 10. Quantities

**Results → Quantities** appears when your plate has standards with known quantities: how much was in each reaction, read from the standards on the plate (never a fold change). Details: [quantities.md](quantities.md).

* **How do I give my standards their quantities?** If the file declares them (RDML quantities), they are used. Otherwise, on **Design → Set the design on this page → Samples**: select the standards, choose **Standard**, give the highest quantity and the dilution step. **From ng to copies…** works the highest one out from a mass.
* **The standard curve**: Cq of every standard well against its quantity (log scale), the fitted line and its 95 % prediction band, the LOD and LOQ as dashed lines, and every unit read from the curve as a diamond. Curves are per plate, or pooled across plates that carry the same series.
* **The numbers**: slope, efficiency with its 95 % confidence interval, R², the levels, the **limit of detection** (the lowest level detected in at least 95 % of its wells; a logistic fit when levels are partly detected), the **limit of quantification** (the lowest level whose back-calculated quantities have a CV of at most 35 %), and where the quantities came from.
* **Every biological unit**: wells detected, mean Cq, the quantity per reaction with its **95 % prediction interval**, and notes in words when it is extrapolated, below the LOQ or LOD, or not detected. **Flagged** lists only those. On a weak curve (its *g* above 0.05, shown with the curve) the interval is the exact (Fieller) one, which the usual formula would make too narrow.
* **Standards that look wrong**: a standard whose Cq breaks the order of the series (a 2-copy standard coming up before the 1,000-copy ones) or sits far off its line is listed under the curve with what the curve would be without it. qPilot never leaves it out: **Propose leaving these out** puts one proposal per well in Curves, and you decide each, with a reason.
* **How firm is the LOD?** With three or four wells per level, "detected in 95 % of its wells" means every well; the LOD's words say so and recommend ten replicates around the limit. The modelled (logistic) LOD is the better estimate then.
* **Per µL or per ng**: **Set the reaction input…** records what one reaction held (µL of template, ng of input), with a reason. No fold change, call or Decision Card changes.

Wells LinRegPCR calls "no amplification" never enter a standard curve, even when they carry a Cq.

**A run that only quantifies** (*Quantify samples* on Design, [section 6](#6-set-the-design-yourself)): the quantities are the result. Results shows how many sample results are *quantified*, *below the limit of quantification*, *below the limit of detection*, *not detected* or extrapolated, the standard curve, and each sample's quantity with its 95 % prediction interval and what is reported for it; click a sample to see its wells (plate, Cq, detected or not, what each well alone reads as, the one more than 2-fold from the others named). Two Decision Cards hold the choices that can change what is reported: *which wells count as detected* (LinRegPCR's call, or a Cq cut-off at 40, 38 or 35) and *how precise a quantity must be to be reported* (the LOQ line at CV 35 % or 25 %). A card waits for you only when another option changes what is reported for at least one sample, and lists those samples. Controls asks whether leaving a rule's wells out changes what is reported; the report and the exports speak of quantities; the record verifies and re-runs like any other. Gene, Audit, Trace, Claims, Prism and Plan next compare groups, so they are locked with the reason. MCP `qpcr_quantities` reads the same numbers for an agent.

*On a real QuantStudio 3 export* of the corpus (SARS-CoV-2 in wastewater, five ten-fold standards): slope −3.327, efficiency 99.8 % (95 % CI 94.4–105.8 %), R² 0.9954. `qpilot quantify FILE…` gives the same from the terminal, for a plate with no groups too, and `qpilot copies --ng 1 --length 3000` converts a mass to copies. Method card: [methods/absolute_quantification.md](../methods/absolute_quantification.md).

## 11. Controls: the Run Gate and melt curves

**Controls** says what the controls on each plate say, and whether any of it changes a call. The shipped rule pack (`research-default` 1.4.0; every threshold and its source in `packs/research-default.yaml`) checks every plate:

| Rule | What it checks |
|---|---|
| G-TYPED | that the plate has wells typed as controls |
| G-NTC-1 | amplification in a no-template control near the study samples (a primer-dimer in an NTC is a warning, from its melt: a peak at least 3 °C below the product; an internal positive control is not judged, it is meant to amplify there) |
| G-NAC, G-NRT | amplification in a no-amplification control; the genomic DNA share from the no-RT control |
| G-POS, G-STD | a positive control inside its window; the standard curve |
| G-REP | the spread of technical replicates (it proposes leaving out the well farthest from the others, or the sample; when two wells are equally far, as with duplicates, it proposes the sample only: the spread is not one well's) |
| G-RT | the spread of reverse-transcription replicates (when the sheet's `rt_replicate` column marks them) |
| G-INSTR | what the run file says about the run: completed, paused, lid opened, calibrations past expiry, holds off their setpoint |
| G-MELT | one product at the assay's melting temperature |
| G-IPC | inhibition: a study well whose internal positive control (a target named IPC or IAC) comes up 3 or more cycles later than in the no-template wells, or where nothing amplified |

Rules label; a person decides. For every rule that warns or fails and points at wells, qPilot re-runs the whole analysis without those wells and says whether a call changes ("Leaving these 2 wells out changes no call").

* **In one line**: the headline, the verdict counts (Fail / Warn / Pass / Not applicable) and what to do.
* **Plates**: one button per plate with its worst verdict; pressing one filters the checks to it. A plate with no wells typed as controls is "ungated".
* **Rule checks**: warn and fail first (filter by verdict, rule and plate); each row opens to the reason in words, the wells it points at and what leaving them out changes.
* **Melt curves (G-MELT).** For SYBR Green or EvaGreen assays exported with their melt curves, G-MELT checks that every amplified well melts as one product within 1 °C of its assay's Tm (the Tm the file declares, else the median of its study wells), counts extra peaks, and says what melted in the no-template controls: a peak at the product's Tm is a contamination candidate, a peak at least 3 °C below it a primer-dimer candidate (usually harmless there), and a peak closer below, or above, another product (a shorter product or a variant amplicon can melt a degree or two below the intended one). The 3 °C is a lab-editable default (`dimer_min_below_c`). Open a G-MELT check to see the wells' −dF/dT; the shaded band is the expected Tm ± tolerance. A single peak does not prove the intended amplicon (MIQE 2.0). `qpilot melt FILE…` prints the same from the terminal. *On the hmuY LightCycler 96 plate of the corpus*, HmuYPe melts at 82.0 °C and 16S rRNA at 87.1 °C, and every judged well melts as expected.
* **Internal positive controls (G-IPC).** On a multiplex plate with an IPC, G-IPC flags the samples whose control came up 3 or more cycles late (possible inhibition), priced like every other warning. An IPC that did not amplify beside a target that did is not inhibition (a strong target can use up the reaction first). The 3-cycle delay is a lab-editable default. *On the QuantStudio 7 Pro eDNA plate of the corpus*, sample M22's wells come up 3.5 to 4.2 cycles late.
* **Decision Cards from the controls**: a card exists only when leaving a rule's wells out can change a conclusion. **In a Studio session you decide it here**: choose an option and say why. Leaving wells out writes one entry per well to the session's record, analyses the study again and carries your Decision Card choices; **Put the wells back** undoes it, with a reason. An agent can only ask. A study analysed outside Studio is read-only here: open its file in Studio to leave wells out.
* **What to repeat**: how many sample × gene items are worth a look, how many change a call, and the repeat plate (download as CSV); the full list is in the Run Review ([section 17](#17-report-methods-miqe-the-run-review-and-exports)).
* **Run files.** An RDML file names the instrument and the run date at most, so G-INSTR is "not applicable" until it reads a run file. Link the file your instrument wrote (an `.eds`, a QuantStudio results export or CFX run information) to its plate on the **Run files** card, or from the plate's G-INSTR check. The link is kept for every analysis of the file; **Unlink** removes it. If you opened your instrument's export and it carries the run's own record, G-INSTR reads it without a link. Linking changes no number, and serial numbers never leave your computer.
* **RT replicates (G-RT).** When your sample sheet's `rt_replicate` column marks samples of one biological unit reverse-transcribed separately, each unit and gene gets a verdict: a range of one cycle or more between the RT replicates' mean Cq is a warning, priced like every other.

*On the demo:* no RT replicates are marked, the file is RDML and the demo has no melt curves, and the plates have no internal positive control, so G-RT, G-INSTR, G-MELT and G-IPC are "not applicable", each saying what would let it check.

## 12. Gene

Open a gene from the Results map or table, or from **Go to a gene** (⌘K). `[` and `]` go to the previous and next gene. Without a gene in the address, the page lists every compared gene to choose from. With several comparisons, a picker chooses the comparison the page follows.

The header gives the gene's name (with a **Headline gene** badge for the study's headline genes), the fold change with its 95 % confidence interval, the p-value, the number of units per group, the **confidence** level with its reasons, and the **audit verdict** ("Not audited yet" before the audit has run). **Copy summary** puts a plain-text summary on your clipboard.

* **What holds.** How often the same call comes out when the analysis is done another way, and a strip with every analysis as a dot on the fold-change axis, coloured by call. **Which analyses** switches between *qPilot's grid* and *The audit* (once it has run), each with its own count.
* **One choice at a time.** For each decision, a dot per option, with every other choice as planned. A ringed dot changes the call on its own.
* **Your samples.** Each biological unit's value relative to the second group's mean, by group. Without an audit it comes straight from the engine: replicate wells are small dots on the unit's line, and each group's mean has its 95 % CI. Click a unit to open its wells and curves, with badges such as "Leaving it out changes the call", "No Cq: never amplified" and "Flagged by LinRegPCR". An outlier is a place to look, not yet a reason to remove it.
* **What changes it, what it leans on, what to do** (after an audit): the choices that flip it, the samples that change the call on their own, and what to check or fix.
* **Decision Cards that affect this gene**, each marked "Can change the call alone" or "Does not change the call alone".
* **Assay and wells** and **Reference genes** (geNorm stability).
* **Figure**: the gene's figure for a lab meeting or a paper, as decided on the Decision Cards: each dot one biological unit, the bar its group's mean with the 95 % confidence interval, the call. **SVG** (editable), **PNG** (300 dpi), **Data** (CSV) and **Copy caption**. The same figures for every headline gene come from Report → Export.

## 13. Audit

The audit re-runs your **confirmed** study under every combination of eight analysis decisions (efficiency model, flagged wells, late Cq, empty wells, which control genes, where to cut the groups, which test, correction for many genes), nine when the design has technical replicates (how replicate wells are combined): 90,396 analyses on the demo, about 50 seconds. It first checks that its own baseline reproduces qPilot's results gene by gene; if it does not, it refuses and writes nothing. It then gives each gene one of the six verdicts of [section 3](#3-three-scales-you-will-see-everywhere). A verdict counts only the audit's reasonable set (144 analyses on the demo); the rest are there so that you can see how far a choice would take a result. The audit changes nothing: it writes its own folder beside the Analysis Record, with a checksum for every file and the decision chain it describes.

* **Not run yet:** the page explains what the audit does and shows what it will cover (analyses, genes compared, samples, sets of reference genes), with **Run the audit** (a job with stages; its longest stage says how far it has come). Running it again keeps the earlier audit.
* **Technical replicates:** each biological unit's wells are combined as qPilot combines them (the mean of their log2 amounts); with three or more wells per value the audit also tries the median well and leaving out one well outside the expected spread. The page says how, before and after the run.
* **Several comparisons:** the audit audits the first comparison and says so. It runs only when the correction changes none of that comparison's calls (so its baseline reproduces qPilot's), and it does not audit a paired comparison or a pooled-variance one (Dunnett, Tukey).
* **Cannot run:** an install without the Decision Simulator, a marker split whose cut-offs are not 10/15/20 %, or a comparison it does not audit (above). The page says which, in words.
* **Done:** four tabs, **Study**, **What-if lab**, **How it works** and **Verify**.
  * **Study:** the verdict counts, the map, the calls that one choice changes, how much of the spread each decision explains, reference-gene stability, "fix these first", and the queue of data issues it found; an issue about a choice offers **Try this choice in the What-if lab**.
  * **What-if lab:** one menu per decision, with the options grouped by how defensible they are; every gene is shown from the planned analysis to your chosen one, changed genes first. Nothing is stored and nothing is decided here.
  * **How it works:** the stages with this audit's own numbers, what is varied at each stage, the verdict rules, the known-answer tests and the audit's limits.
  * **Verify:** "Is this audit intact, and is it this study's?": the audit's checksums, whether it reproduces qPilot's result, whether it belongs to this study's record, and whether decisions were made since it ran.
* **Audit shown:** if you started `qpilot app --audit DIR` (or `qsim app --results DIR`), a menu switches between this study's audit and the attached results folder, shown read-only.

## 14. Trace: where to look

**Trace** follows any call down to the samples, wells and plates behind it. Every number is the engine's, recomputed exactly with samples set aside; reading it changes nothing. The overview says how many calls change when one or two samples are set aside, and which samples have a control-gene well far from what their other control genes predict.

**Where to look** follows a gene's result, one sample or one well (`PLATE:WELL`) back through the normaliser and the reference wells to the plate controls, and lists the places to look first: the sample, plate and well, what is unusual there (for example "one reference well disagrees with the sample's other reference wells"), what to check, and what each option would do: keep it, read that well from the sample's other reference wells (a what-if, shown, never chosen), or set the value or the whole sample aside. Places are ranked by what their options do: change a call, move a fold change beyond its confidence interval, or change nothing. With several comparisons, Trace follows the comparison you pick, and its call is the corrected one.

* **How do I leave out the well Trace points at?** On a place where an option **changes a call**, press **Decide…**, choose the option and say why. In a Studio session the wells leave the analysis (one entry per well in the session's record), the study is analysed again and Trace waits for it; your Decision Card choices are carried. **Set aside from Trace** lists what you set aside, each with **Put the wells back** (with a reason).
* **A study analysed outside Studio** has no inbox: Decide… records your decision on a card and the numbers stay as analysed. Open the file in Studio to apply it.
* **An agent's request.** An agent can ask you to set wells aside at a place (`qpcr_request_set_aside`). The place then shows an **Agent asked** badge and "An agent asked to … because …"; Decide… offers the asked option first: **Approve** it, or **Turn down the request** with your reason. Your click answers every request waiting at that place.

*On the demo:* CAMTA2 (no call) points first at tumour 2016, plate HMBS_20080318, well K22: that HMBS well reads Cq 46.1 while the tumour's four other reference wells agree, so all 58 of its values read 5.55× too high; reading the well from the other four makes CAMTA2 down. Method card: [methods/trace.md](../methods/trace.md).

## 15. Claims

**Claims** checks what your paper says against this study's own record. Paste a results paragraph, a figure legend or an abstract (up to 5,000 characters; checked on this computer and not stored) and press **Check claims**. **Try an example from this study** offers sentences written from your own study, some true and some not.

Each claim is read by fixed rules, never judged by a model:

* genes by name, assay name or HGNC alias (survivin is BIRC5);
* the direction (up, down or unchanged) between the study's groups, either way round;
* fold changes (3.6-fold, 3.6×, a 72 % decrease, log2 FC), p-values and words like *significantly*;
* robustness words such as *robustly*, the normaliser, n and efficiency ranges.

Each claim comes back **Supported**, or not, with the study's own numbers and where they were read from: the planned analysis, every choice qPilot checks and, if run, the audit. A claim about groups the study does not compare (a clinical status, a stage, another gene's level) is **Not supported: different groups**, and says what the study compares. A p-value stays with its own gene, and a sentence about normalisation applies only to the claims it is about.

## 16. History

**History** replays every decision and shows what each one changed. The **timeline** lists every point of this analysis's history (the design and curves stages, the choices, Prism, and earlier analyses of the same file); pick one, or use ← and →, and the robustness map shows the calls in force at that point, read from the study's own grid of analyses. **Replay from the start** steps through it. Each step says who chose what and when ("qPilot (automatic) chose …", "Decided by you"), and whether it changed a call. The chain's head and whether every hash checks out are shown at the top. With several comparisons, History replays the comparison you pick.

## 17. Report: Methods, MIQE, the Run Review and exports

**Report** writes your study up from its own numbers. Its parts, in order:

* **Summary**: plates, samples, reactions, genes compared, calls, and both robustness counts (with **Why two counts?**).
* **Reviewer's report**: what a careful reviewer would raise, most severe first (major points, minor points, notes), each read from this study's numbers, none a model's opinion, with a link to where to act.
* **Run Review** (below).
* **Methods**: a paragraph to paste, with the methods and their references (and the comparisons, the normaliser and the quantities when the study has them).
* **MIQE 2.0 checklist**: each item answered from the study, or marked as missing.
* **Limitations**, the **Study passport**, and **Every number**: each number the report cites, its value and where it comes from.

**The Run Review** is one page for whoever reviews someone else's run: the headline genes (with several comparisons, each comparison named), what the data cannot show, **what to repeat and why**, the Run Gate per plate, and every sign-off so far. qPilot never passes or fails a run.

* **What to repeat** lists each sample × gene worth re-running, ranked by what it does to the calls (changes a call, beyond the CI, no value, not known, changes nothing), with every reason in words: the Run Gate's warnings and failures, wells a person left out and why, samples in no comparison, no amplification where the gene amplified in most other samples, Trace's places. **The repeat plate** puts every repeated sample on a plate with all its reference genes, and per assay an inter-run calibrator, no-RT and no-template controls; **Download the repeat plate (CSV)** gives the planner's plate format (plate, well, sample, group, target, type) for a plate-setup program or a pipetting robot. Items that change no call go on the plate only when you ask. Re-running is your call. *On the demo:* 182 items, 5 of which change a call.
* **Sign off** with **Accept**, **Repeat** or **Discuss**, a comment and your name: it goes into the decision record as yours and changes no result. If something was decided while you were reading, the review is shown again and you sign off on what is there now.

**Export: numbers, figures and the report.** Every file is written from the study's own numbers, as decided on the Decision Cards; when a choice you made is not the recommended one, the recommended analysis comes too, marked as such. Strings from your files are kept as text, never as formulas.

* **Excel workbook**: real numbers you can calculate with: each gene's fold change, its 95 % confidence interval as two columns, p and n; each biological unit's ΔCq and relative quantity; every well's Cq, N0 and efficiency, and why a well was left out; Trace's places to look; the decisions, the settings and Methods; the standard curves and quantities when the plate has standards.
* **CSV tables**: the same tables, one file per table, for R, Python or Prism.
* **Figures**: a figure per headline gene, each dot a biological unit, the group mean with its 95 % CI, the call: SVG you can edit, PNG at 300 dpi, the data behind it and its caption.
* **Journal supplement**: one zip with the workbook, every table as CSV, the MIQE 2.0 checklist, the figures, your RDML file with qPilot's Cq, N0 and left-out wells written into it, and the Analysis Record anyone can check and re-run.
* **The report** itself: the **Study passport** (one HTML file a reviewer opens offline, with a fresh Analysis Record beside it), a **printable page** (to print or save as PDF), and **Markdown**.

The terminal does the same: `qpilot export xlsx|csv|figures|supplement --out FILE` and `qpilot report run-review --repeat --out review.html`. What each file holds: [exports.md](exports.md).

## 18. Plan next

**Plan next** plans the next experiment from the noise this study measured: how many samples each gene needs, what a design can detect, and the plates to run it on.

* **What this study measured**: the groups compared, the noise between samples (σ, log2) across genes, the conclusion rule, how the plates were laid out and each assay's efficiency (assays outside 90–110 % are named, to check with a standard curve).
* **How many samples, and what they can detect**: move the sliders (the change worth finding, the power, the samples per group) and choose the genes of the next experiment; every number is qPilot's plan arithmetic and a simulation of qPilot's own rule. The plan starts at **2.5×**, because a true 2-fold change measures below 2-fold about half the time, so the 2-fold rule would call it only about half the time however many samples you run.
* **Plates you have** (optional) lays the plan out on your plates.

Before the first plate, `qpilot plan --fc 2.5 --sd 0.5 --n 6` does the same from the terminal; `--sd-rt`, `--sd-well`, `--n-rt` and `--n-tech` add the replicate budget (biological, RT and technical replicates in one formula), and `--cq` sets the well noise from Poisson sampling at that Cq. Method card: [methods/replicate_budget.md](../methods/replicate_budget.md).

## 19. Prism

For people who finish their figures in GraphPad Prism: "Hand GraphPad Prism numbers it cannot misread, and see what changed when the tables come back." qPilot does not replace Prism and is not affiliated with GraphPad Software or Dotmatics. The section is open once you have confirmed the analysis choices on Results, and a row of steps at the top shows where you are.

* **What the usual route into Prism would change** shows how often the usual Excel-to-Prism routes (2^-ΔΔCq with a t-test on the linear scale, the same with Student's test, ΔΔCq at an assumed efficiency of 2.0) would change a conclusion on this study. *On the demo:* 14 of 58.
* **The Prism project** says which genes get a table, the test, the graph and the caption. It is a proposal like any other: press **Draft the Prism project**, read it, and accept it. A project you accepted stays valid as long as no decision changes a number in its tables ("still current"); otherwise the page asks you to draft it again.
* **What Prism will get** previews the tables of one gene: every biological unit, and the group means with their 95 % confidence intervals.
* **Send to Prism** writes a **Prism project** (`.pzfx`) that opens in GraphPad Prism as it is (double-click it, or File > Open): one table per gene, a table of all genes, and an Info sheet with who decided what. There is no template to build and no script to run. The page gives the clicks for Windows and macOS that add the t test and the graph (Prism's analyses and graphs are a part of the file only Prism writes). The bundle also holds the same tables as CSV. **The project has not yet been opened in a real Prism seat by the qPilot team** ([prism.md](prism.md)); the table of all genes needs Prism 9 or later.
* **Round trip: what changed in Prism.** In Prism, make your edits (exclude a value, delete one, change one) and save the project. Then, under **Round trip**, choose the **bundle sent from this session** and **the project Prism saved (.pzfx)** (it can come from any computer; it is read here and kept with the bundle), or give the folder or file it was saved in, and press **Read what came back**. Every value changed, excluded or deleted comes back as a question with what accepting it would change, computed by qPilot: for example "ODC1 3.590× → 3.319×, still up; 0 of 58 conclusions change". When several samples are excluded, each card also shows what they do together. Accepting one re-runs the analysis (your Decision Card choices are carried). If Prism sent back exactly what qPilot wrote, the page says "No differences".

`qpilot export prism --out DIR` writes the same project from the terminal (`--scripts` adds the older Prism scripts for a template made by hand).

## 20. Record

**The decision chain**, newest first: every entry has its sequence number, the card and the option, who decided (a person, an agent or the system), the reason, the time, its hash and the previous entry's hash, and its status (applied, waiting, turned down, out of date). A carried entry is marked **Carried**, with the earlier analysis's entry it names. Each entry's hash covers the entry before it, so changing any line breaks every later link. Before the study is analysed the section says the record starts when the design and the curves are confirmed.

* **Export the Analysis Record** writes one zip: your input file (when it is still on disk), the design, every decision with its reason and actor, the results, and their checksums. The page then shows the record's id and chain head and the file to download. If decisions were made after an export, it warns: "Decisions were made after this record was exported; export again to include them."
* **Verify a record** takes a zip (yours, or one you received; it is read on this computer only) and checks that every file matches its checksum, that the files agree with the chain, and, if there is one, that the audit bound to it verifies and belongs to it. The answer is "This record checks out" or names what does not: "This record was altered or damaged after export: decisions.jsonl", the entry where the chain breaks, or "not a qPilot record".
* The page also gives the commands that repeat the checks outside it: `qpilot verify <record.zip>` and `qpilot rerun <unzipped folder>` (re-analyses the input and compares every result byte for byte).

The chain is **tamper-evident, not tamper-proof**: nothing is signed, so someone who rewrites every hash consistently is not detected unless you compare the record's id with a copy kept elsewhere. qPilot is not a 21 CFR Part 11 system.

## 21. Agents

For agents that work with qPilot over MCP (Claude Code, for example). "AI agents work on your studies through qPilot's MCP server. They read, open and propose; a choice that can change a conclusion always waits for a person."

```bash
claude mcp add qpilot -- qpilot serve
```

* **Connect an agent** shows this command with a copy button, and the rules qPilot's code enforces whatever an agent or its model says.
* **The tools** (33: 28 `qpcr_*` and 5 read-only `sim_*`) are grouped by what they can change: **Read** (studies, genes, comparisons, per-unit values, quantities, melt curves, the repeat plan, the audit; they change nothing), **Open** (open a file as a study or a Studio session; they decide nothing), **Propose** (add a proposal to a Studio inbox; only a person accepts it), **Request a decision** (ask for a choice on a Decision Card, or ask you to set wells aside; one that can change a conclusion always waits for you) and **Write a file** (`qpcr_export`: new export files only; it decides nothing).
* **Requests waiting for a person** lists every agent request in every study, oldest first, with the agent's reason and what it asks about (a card, or which wells and where). Choose **Approve** or **Turn down** and say why. A request to set wells aside is also shown in Trace, at its place ([section 14](#14-trace-where-to-look)). The agent bell in the top bar counts them.
* **Recent agent activity**, newest first: the requests and choices agents made on Decision Cards, and the proposals they made in Studio inboxes. For a study whose design and curves are not confirmed yet, requests and entries are counted but not listed: every tool that reads results answers "results hidden" until you confirm both.

**What agents may do on their own** is a setting of each study, with the autonomy switch in that study's top bar; a new study starts at **Suggest**. In *Suggest* every request from an agent waits for you. In *Decide and tell me* an agent may apply a choice that cannot change any conclusion, and you are told; everything else still waits for you. A choice that can change a conclusion is always yours. An agent that can run commands as you can still act as you; give agents MCP access, not your shell. The tools, one by one: [agents.md](agents.md).

## 22. Ask

Press ⌘J (or the Ask button in the top bar) and ask the open study a question in plain words; **Try one of these** offers questions written from your own study. Genes can be named by their HGNC alias. Until the design and the curves are confirmed the drawer says it waits until the study is unblinded. **Answer from** chooses between the study's own engine and, once the audit has run, the audit's.

Every answer says which tool answered it, how the question was routed (the model, keyword matching, or fixed reading rules), who wrote the words (the model, with every number checked, or qPilot's checked template), and a table of **the numbers in this answer, from the study's facts**. Text that contains a number the engine did not produce is discarded. **What the model saw** shows the exact last payload this qPilot process sent to a model.

Ask never changes a choice, at either autonomy setting: it only reads. If you ask it to change one, it writes nothing, says "Ask never changes a choice" and names the Decision Card where a person decides it.

## 23. Sheet check

**Sheet check** (under *Lab* in the rail) recomputes your own ΔΔCq spreadsheet (`.xlsx` or `.csv`) from its own Cq values: how many fold changes reproduce, the first column and row that differ, and the known slip that reproduces it (an inverted sign, the exponent applied twice, statistics run on fold changes, …). Compared with a study, genes whose arithmetic reproduces but whose fold change differs from qPilot's are a difference of method, not a slip. qPilot guesses which column holds what and says so until you **confirm the mapping** (change any column first). Your sheet is never edited, nothing is saved, and its sample and group names are not shown back.

## 24. Instruments

**Instruments** (under *Lab*) is your lab's working memory for each instrument: its latest calibrations and their age, open incidents, and its logbook (a hash chain, so an edit shows). An agent may only propose an incident; you **confirm** it or **turn it down** here, and note what fixed it. Log calibrations, part changes, service visits, moves and notes yourself. **Read a run file** (`.eds`, a QuantStudio or CFX export, RDML) shows what the file says about the instrument and the run (calibration dates, pauses, an aborted run); serial numbers never leave your computer, and the first file from an unknown instrument asks once which instrument it is. **Lookback** answers "which of my conclusions used this instrument between these dates, and what changes without those runs?"; it writes nothing.

## 25. Settings

* **Model.** The provider (none, a local OpenAI-compatible server, or Anthropic) comes from the environment (`QPILOT_MODEL_PROVIDER` and the other variables in [agents.md](agents.md)); the page shows its status and reason, **Check connection**, and **Test this model**, which scores the model on your study (correct answers, invented numbers caught, safety, fallbacks, latency). The page has no field for an endpoint or a key, on purpose.
* **What agents may do on their own** explains the two levels; it sets nothing. The setting belongs to each study ([section 21](#21-agents)).
* **Theme** (system, light or dark; saved in this browser).
* **Start a fresh demo…** asks first, then moves the demo's earlier work aside to a kept folder (`studies-archive/`, next to the studies folder; never deleted). Your own studies are not touched.
* **What qPilot never does**, and **This install**: the version, the curve method and its commit, whether the audit is installed, the Python version and the studies folder (with a copy button).

## 26. Keyboard

| Keys | Action |
|---|---|
| ⌘K / Ctrl K | Command palette: go to a section, gene or card; actions such as Propose, Run the audit, Export |
| ⌘J | Ask drawer |
| ⌘O | Open a file |
| `g` then `d` / `c` / `r` / `a` / `p` / `e` | Design / Curves / Results / Audit / Prism / Record |
| `j` / `k` | Next / previous card (the inbox, the Decision Cards) |
| `a` / `e` / `x` | Accept / Edit / Reject the focused proposal |
| `[` / `]` | Previous / next gene (and plate, on the Curves plate) |
| `Enter`, then ⌘Enter | On a Decision Card: focus the reason, then decide |
| `?` | Shortcut sheet |

Everything can also be done with the Tab key, and every control shows where the focus is.

## 27. When something does not work

| You see | What it means | What to do |
|---|---|---|
| "Open the link qPilot printed in your terminal" | This tab does not carry this launch's key (the page was restarted, or opened by typing the address) | Open the link from the terminal where `qpilot app` runs |
| "Something was decided since you loaded this" | Another tab or an agent changed the record while you were reading | Read the current state shown and decide again |
| A section is locked | The step before it is not confirmed | The lock says which one |
| The bell says "Getting ready" | qPilot is reading your studies after a start | Work meanwhile; it takes a minute or so |
| A file is refused on Open | qPilot could not read it, or it is not a qPCR run (for example an isothermal plate read), or two RDML files were dropped together | The refusal says why; open one RDML file at a time; [conformance.md](conformance.md) lists what is read |
| Every gene is capped at Moderate | The export's curves were most likely baseline-subtracted (or qPilot could not tell) | Decide the Import Trust card on Results |
| "The demo study is not downloaded yet" | The demo is not on this computer | Click **Download 7.0 MB and open** on Open, or run `qpilot fetch-demo` |
| The audit is refused | Its baseline does not reproduce qPilot, or the comparison is one it cannot audit yet (paired, Dunnett or Tukey, or a correction that changes a call) | The page gives the reason in words |
| Send to Prism refuses a group name | A group or unit name starts with `=`, `+` or `@`, which Prism would read as a formula | Rename it on the Design page (any other letters, digits and signs are fine) |
| Gene, Audit, Trace, Claims, Prism or Plan next is locked in a quantification | Those sections compare groups; a *Quantify samples* study has none | Its result is on Results → Quantities |
| No Quantities on Results | The plate's standards have no quantity yet | Give them on Design → Samples (Standard, top quantity, dilution step) |
| The model chip says "not answering" | The model is configured but does not answer; hover for the reason | Rules answer alone meanwhile; check the endpoint and name |
| The live dot is not green | The page lost its connection to qPilot | It reconnects by itself; if not, is `qpilot app` still running? |

## 28. What the page never does

* It never makes a choice that can change a conclusion; those always wait for a person.
* It never shows a group difference (fold change, p-value, direction) before the design and the curves are confirmed, and the server, not the page, enforces this.
* It never shows a number the engine did not compute: there are no sample numbers, no placeholder genes, no example charts.
* It never loads anything from the internet and never sends your data anywhere on its own.
* It never records a decision as anyone but the person at the page.
* It never claims a confidence in percent: levels are ordinal, with reasons.
