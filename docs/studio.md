# qPilot Studio: from the instrument export to GraphPad Prism

Studio is a local page between your qPCR instrument and GraphPad Prism. **The AI proposes. The
engine checks. You decide.** The AI (fixed rules, a language model when one is configured, the
Curve Judge) proposes the study design and the curve calls; the deterministic engine checks each
proposal and computes every number; nothing changes the analysis, the Analysis Record or a Prism
file until you press a button. Research use only.

```
qpilot fetch-demo            # once: the public Vermeulen dataset used below
qpilot studio [--port N]     # opens on http://127.0.0.1:<port>, this computer only
qpilot studio demo --check   # the whole walk-through below, scripted, no browser
```

The line under the title says which model Studio uses: **none** (the rules propose alone),
**local** (sample names go only to that local endpoint, as quoted data), or **REMOTE — names
pseudonymised** (sample names are replaced by pseudonyms before anything leaves the computer).
It also says whether that model answers. Studio asks it a one-token question at most once a
minute, in the background, so the page never waits on a model that does not answer (at most
2 seconds, the first time). Until the first answer the line says **checking whether it
answers**. A model that is configured but does not answer is shown as **configured but not
answering**, with the reason (for example, the endpoint refused the connection, or HTTP 404:
is the model pulled?). Each Propose still tries it, then the rules propose alone, and the
report says why. A model whose configuration is wrong (an unknown provider, a missing
endpoint, a remote endpoint without `QPILOT_MODEL_PROVIDER`) shows **none**, with what is
wrong. If the Design Interpreter itself fails, the rules' proposals are still stored, with a
note.

## The page

* **1 · Intake** (left). Your RDML file (leave it empty for the cached demo), an optional sample
  sheet (.xlsx or .csv) and one optional sentence about the experiment, then **Open**. Opening
  analyses nothing and proposes nothing. Below it, the stage strip: Design (blind) → Curves
  (blind) → Choices → Prism draft → Round trip, each open, confirmed or not open yet, with what
  is waiting and what blocks it.
* **2 · What the AI thinks** (middle). The inbox of a stage, one card per proposal, the ones the
  engine contradicts first. Every card has the same six parts:
  1. **Proposal**, in plain words, with the other readings it considered;
  2. **Why**: each source is a fold-out — a name shows the original text from the file (quoted;
     text that reads like an instruction is marked and never obeyed), a sheet cell shows the cell,
     a well can be plotted under "Curve of a cited well";
  3. **Engine check**: *consistent* (nothing refutes it; a check can refute, never prove),
     *contradicted* (accepting needs a reason) or *cannot check*, with the rules and their numbers;
  4. **Consequence**: hidden in the blind stages except "this matters for at least one
     conclusion; decide on the evidence" (or ask "Does this matter?", answered yes or no: the
     engine builds each reading the way accepting it would, from your accepted decisions with
     this one in place of any earlier decision on the same item); shown in full in the round
     trip;
  5. **Level**: an ordinal level with its reasons, never a percentage;
  6. **Actions**: Accept, Edit (change the fields, then accept; the edit is checked again), or
     Reject with a reason. A footer says who made the proposal (a rule, a model with its name and
     prompt hash, or an agent) and, for a language model, what the model saw.

  **Accept all consistent…** first shows the exact list it covers (never a contradicted or
  cannot-check proposal); a second click accepts exactly that list, one record entry each.
  **Reject all contradicted AI calls…** does the same for a model's or an agent's proposals the
  engine contradicts, with one reason you type. **Confirm this stage…** first shows what the
  confirm covers; only **Yes, confirm** confirms.
* **3 · Prism preview** (right). Hidden until you have confirmed both blind stages. Then: the
  study summary, how often the usual Excel→Prism routes would change a conclusion on this study,
  the Decision Cards (the Choices stage), the Prism project, a preview of the tables, test and
  graph (every biological unit with the group mean and its 95 % confidence interval, an
  approximation of what Prism draws), **Send to Prism**, and the round trip.

## The demo, stage by stage (measured)

These are the numbers `qpilot studio demo --check` checks on every run (it exits 1 if one
differs); see also [studio-measured.md](studio-measured.md).

1. **Design (blind).** The rules make 131 proposals (no model). The demo's published design is
   one of them. "Accept all consistent" lists 121; the 9 left are contradicted by the engine: the
   seven conc-64 competimer standards never amplified, the comp_50 series has R² 0.707, and the
   standard series on the ALUsq plate has R² 0.694. Reject them with a reason, then confirm.
2. **Curves (blind).** The Curve Judge disagrees with LinRegPCR on 166 study wells; only ALUsq's
   could change a conclusion, so those 110 wells are listed, one card each, each contradicted by
   LinRegPCR's complete fit (`D-CURVE`) and each saying only that it matters. Reject them with
   one reason, accept LinRegPCR's call rule, confirm.
3. **Choices.** Results appear: ODC1 3.590× up, every conclusion recomputed under 744 reasonable
   analyses; the usual route (2^-ΔΔCq per sample, Welch on the linear scale) would change 14 of
   58 conclusions (21 with Student's t test, 4 with ΔΔCq at an assumed efficiency of 2.0).
   Decide the cards, confirm.
4. **Prism draft.** Draft the project, accept it, press Send to Prism: the bundle (one CSV per
   gene, `run.pzc`, `send_back.pzc`, provenance) is written into a new folder; Studio starts Prism
   only when Prism is installed, and otherwise says so and offers the bundle as a zip.
5. **Round trip.** Excluding ODC1's sample 1496 in Prism comes back as one question: "Reason?",
   with its consequence — ODC1 3.590× → 3.319×, still up; 0 of 58 conclusions change. Accepting
   it (with the reason) re-runs the analysis: the page then shows only the new analysis (ODC1
   3.3×) and the Choices stage opens again for it.

### Several exclusions at once

Each exclusion's consequence is computed by the engine on top of the exclusions you have already
accepted since the export, and records that basis (the analysis, its decision chain, and the
accepted exclusions). When Prism sends back more than one exclusion, every question also shows
what **all the exclusions found in this round trip do together**. One at a time, each may change
nothing, while together they change a call. On the demo, clearing NM23A's units 1824, 1936,
2530 and 2784 gives four questions that each change no conclusion. Every card then says that
together they change NM23A's conclusion, and the round-trip note gives the count for all of
them.

When you accept one, Studio reads the same sent-back folder again and replaces the other
pending questions with fresh ones, computed on top of the one you accepted. A question whose
basis no longer matches and could not be recomputed (the sent-back folder has moved, say), or
whose exported analysis has had its decisions changed since, says **Out of date** on its card,
shows none of its numbers, and cannot be accepted until you read what Prism sent back again
(**Round trip**). So the numbers you read are the ones accepting gives.

## What keeps it honest

* **Only your click decides.** Every accept, edit, reject, decision, Prism bundle and Prism launch
  is a button that passes `actor="human"`; loading the page or picking a stage, card or gene only
  reads. The service and the proposal store refuse anyone else in code
  (`tests/studio/test_studio_app.py` runs every handler against a recording fake).
* **Blind means blind.** Before both blind stages are confirmed the page reads nothing of the
  analysis, so no gene conclusion, fold change, p-value, card or Prism preview can appear; every
  view is recomputed from the service on each click, and a re-opened stage hides earlier numbers
  again.
* **Local only.** The same hardening as `qpilot app`: 127.0.0.1, telemetry off, foreign `Host`
  headers refused, no monitoring or run history, files served only from a private export folder;
  the page's actions are hidden from the API page and the Gradio client libraries.
* **Escaped.** Names from the file and the sheet, model and agent text are shown as text, never
  as markup.

## Limits

* Prism itself: the bundle follows GraphPad's documented script language but has **not yet run
  on a real Prism seat**, and the template files are made once by hand
  ([prism.md](prism.md)). The graph in the preview is an approximation.
* "What the model saw" shows the last model call of this qPilot process (kept in memory only);
  the card says when it is that card's own payload.
* Not in Studio yet (use `qpilot app`): Undo on a Decision Card, and turning down an agent's
  pending request on a card.
* The curve plot is the curve as the Curve Judge reads it (each curve divided by its minimum,
  cycles 1–40), not the instrument's raw fluorescence.
* The Curve Judge cannot score a curve whose minimum over cycles 1–40 is not a positive number
  (a baseline-subtracted or offset export). Such a well has no Curve Judge call at all: it is
  never shown or proposed as "not amplified", and the curves report counts these wells
  ("LinRegPCR alone there").
