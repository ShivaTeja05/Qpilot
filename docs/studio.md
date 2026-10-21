# qPilot Studio: from the instrument export to GraphPad Prism

Studio is the part of qPilot between your qPCR instrument and GraphPad Prism. **The AI proposes.
The engine checks. You decide.** The AI (fixed rules, a language model when one is configured, the
Curve Judge) proposes the study design and the curve calls; the deterministic engine checks each
proposal and computes every number; nothing changes the analysis, the Analysis Record or a Prism
file until you press a button. Research use only.

Studio is a service (`qpilot/studio_service.py`) that the one page, the MCP server and the scripted
check all use. You meet it on the page's sections **Design**, **Curves**, **Results**, **Prism**
and **Record**; this document keeps Studio's rules and its measured behaviour, and
[user-guide.md](user-guide.md) is the guide to the page itself.

```
qpilot fetch-demo            # once: the public Vermeulen dataset used below
qpilot app                   # the page, on http://127.0.0.1:<port>, this computer only
qpilot studio demo --check   # the whole walk-through below, scripted, no browser
```

## The stages

A session has five stages. The page shows them in the rail and in the next-step banner.

| Stage | Page section | What is decided | Blind |
|---|---|---|---|
| Design | Design | what each sample and gene is, the groups, the comparison | yes |
| Curves | Curves | which wells count as amplified, and by which rule | yes |
| Choices | Results | the Decision Cards: the choices that could change a conclusion; which further choices to test (the efficiency models, opt-in) | no |
| Prism draft | Prism | the Prism project | no |
| Round trip | Prism | what changed in Prism, as questions with their consequences | no |

**Blind** means that nothing that pairs a group with a number (a fold change, a p-value, a call,
a consequence) is shown or sent until a person has confirmed both blind stages. The server
enforces it (an API answer `403 blind`); the page never relies on hiding.

## Which model Studio uses

The model chip in the page's top bar says **none** (the rules propose alone), **local** (sample
names go only to that local endpoint, as quoted data), or **REMOTE — names pseudonymised** (sample
names are replaced by pseudonyms before anything leaves the computer). Settings says whether that
model answers: qPilot asks it a one-token question at most once a minute, in the background, so
the page never waits on a model that does not answer (at most 2 seconds, the first time). Until
the first answer the chip says **checking**. A model that is configured but does not answer is
shown as **not answering**, with the reason (for example, the endpoint refused the connection, or
HTTP 404: is the model pulled?). Each Propose still tries it, then the rules propose alone, and
the report says why. A model whose configuration is wrong (an unknown provider, a missing
endpoint, a remote endpoint without `QPILOT_MODEL_PROVIDER`) shows **none**, with what is wrong. If
the Design Interpreter itself fails, the rules' proposals are still stored, with a note. The
provider, endpoint and key are set in the environment, never on the page
([agents.md](agents.md#which-model-studio-uses)).

## The inbox and the proposal card

A stage's inbox lists one card per proposal, the ones the engine contradicts first. Every card has
the same six parts:

1. **Proposal**, in plain words, with the other readings it considered;
2. **Why**: each source is a fold-out. A name shows the original text from the file (quoted; text
   that reads like an instruction is marked and never obeyed), a sheet cell shows the cell, and a
   well opens its curve;
3. **Engine check**: *consistent* (nothing refutes it; a check can refute, never prove),
   *contradicted* (accepting needs a reason) or *cannot check*, with the rules and their numbers;
4. **Consequence**: hidden in the blind stages except "this matters for at least one conclusion;
   decide on the evidence" (or ask "Does this matter?", answered yes or no: the engine builds each
   reading the way accepting it would, from your accepted decisions with this one in place of any
   earlier decision on the same item); shown in full in the round trip;
5. **Level**: an ordinal level with its reasons, never a percentage;
6. **Actions**: Accept, Edit (change the fields, then accept; the edit is checked again), or Reject
   with a reason. A footer says who made the proposal (a rule, a model with its name and prompt
   hash, or an agent) and, for a language model, what the model saw.

**Accept all consistent…** first shows the exact list it covers (never a contradicted or
cannot-check proposal); a second click accepts exactly that list, one record entry each.
**Reject contradicted AI calls…** does the same for a model's or an agent's proposals the engine
contradicts, with one reason you type. **Confirm this stage…** first shows what the confirm
covers; only **Yes, confirm** confirms. If the inbox changed while you were looking (another tab,
or an agent), the page says so and shows the current inbox instead of acting on the old list.

After both blind stages are confirmed the page shows the results, the Decision Cards (the Choices
stage; **Also test efficiency models** asks qPilot to propose one more choice of the grid, which
efficiency turns each Cq into a quantity: accepting it analyses the study again with that choice,
whose own card says what each model changes, and the design, so the record, names it; see
`methods/efficiency_model.md`), and the Prism project with a preview of its tables, test and graph (every biological unit
with the group mean and its 95 % confidence interval, an approximation of what Prism draws), then
**Send to Prism** and the round trip.

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
3. **Choices.** Results appear: ODC1 3.590× up, every conclusion recomputed under the 744 analyses
   qPilot checks; the usual route (2^-ΔΔCq per sample, Welch on the linear scale) would change 14 of
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
  the page makes is written as `actor="human"`, set by the server: no request can choose another
  actor. The service and the proposal store refuse anyone else in code
  ([THREAT_MODEL.md](../THREAT_MODEL.md), rows 17 and 31; `tests/core/test_proposals.py`,
  `tests/web/test_studio_flow.py`). Loading the page or picking a stage, card or gene only reads.
* **Blind means blind.** Before both blind stages are confirmed the server sends nothing of the
  analysis, so no gene conclusion, fold change, p-value, card or Prism preview can reach the page
  (row 30; `tests/web/test_studio_flow.py`, `tests/studio/test_mcp_studio.py`); a re-opened stage
  hides earlier numbers again.
* **Local only.** The server answers on 127.0.0.1 only, for requests that carry the launch's key
  and a local host name; it loads nothing from the internet and sends no telemetry (rows 9, 13
  and 24).
* **Text is text.** Names from the file and the sheet, and model and agent text, are shown as
  text, never as markup (row 8).

## Limits

* Prism itself: the bundle follows GraphPad's documented script language but has **not yet run
  on a real Prism seat**, and the template files are made once by hand
  ([prism.md](prism.md)). The graph in the preview is an approximation.
* "What the model saw" shows the last model call of this qPilot process (kept in memory only);
  the card says when it is that card's own payload.
* The Curve Judge reads each curve divided by its minimum over cycles 1–40; the curve viewer
  plots the instrument's raw fluorescence, with the Cq marker and baseline when LinRegPCR found
  them.
* The Curve Judge cannot score a curve whose minimum over cycles 1–40 is not a positive number
  (a baseline-subtracted or offset export). Such a well has no Curve Judge call at all: it is
  never shown or proposed as "not amplified", and the curves report counts these wells
  ("LinRegPCR alone there").
