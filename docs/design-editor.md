# Setting the design on the page (no model needed)

qPilot's rules propose a design from what a file and a sample sheet say; a language model can
propose more from the names. Neither is required: on the **Design** page a person can set every
design item the rules and the model did not propose, for any plate, with no model configured
(`QPILOT_MODEL_PROVIDER=none`). The principles do not change: **you decide, the engine checks,
every choice is recorded with who and why, and the design stays blind** (nothing pairs a group
with a number before the design and the curves are confirmed).

## What you can set

The **Set the design on this page** card has five tabs:

| Tab | What you set | Recorded as |
|---|---|---|
| Targets | each target: **reference gene** (housekeeping), **gene of interest**, or **leave out** (an empty channel, a spike-in; none of its wells is used) | `design.target_role` `{"role": "ref" \| "toi" \| "ignore"}` |
| Samples | select samples (a click, Shift-click for a range, ⌘/Ctrl-A, a name pattern such as `KO*` or `/^S[1-4]$/`, or wells on the plate map: Shift-click a rectangle, a row letter or column number) and set their **group**, **sample type** (study sample, standard with its quantity, NTC, no-RT, no-amplification, positive control, no-target-present, calibrator) or **biological unit** | `design.group`, `design.well_role`, `design.dilution_series` (standards, one series per experiment, quantities in plate order from a top quantity and a dilution step), `design.bio_unit` |
| Paste a list | two columns copied from Excel (sample, group; a third column is the biological unit), matched to the file's names | `design.group`, `design.bio_unit` |
| Comparison | the compared group and the reference group (the baseline the fold change is relative to) | `design.comparison` |
| Sample sheet | download a template pre-filled with this plate's sample and target names, fill it in Excel, attach it to this session (no need to open the files again); the rules then propose from it | the rules' proposals, decided as usual |

Changes collect in a draft ("3 changes not recorded yet"). **Review and record…** shows, before
anything is written, what each change does and the engine's check of it (consistent,
contradicted, cannot check, with the check's words), which waiting proposals it settles, and
what is refused. One reason covers the act and is kept with every item.

## How a change is recorded

Each item is a proposal **made by the person** (`made_by.kind = "person"`) and **accepted by the
person in the same act** (`actor = "human"` for both entries), written with
`ProposalStore.decide_together`: all of it or nothing, in the hash-chained inbox like every
decision. Only a person can make such a proposal: the store refuses `made_by.kind = "person"`
from an agent or the system, and replay rejects a chain where anyone else proposed one.

* A waiting proposal on the same item (a rule's, a model's, an agent's) is **accepted** when it
  says what you set (so who proposed it stays on record), and **rejected with your reason** when
  it says something else. Your standards also settle waiting series and sample types on their
  samples. So the inbox never keeps a question you already answered.
* An item that is already so is not written again.
* The engine checks every item exactly as it checks any proposal. A contradicted item is
  recorded only when you tick "I have read why, and record them anyway".
* The hard bans hold: a declared or confirmed control (NTC, no-RT, no-amplification) never gets
  another type and never joins a group or unit; such an item is refused in words and nothing is
  written. One exception is deliberate: a person may correct a biological unit they (or their
  sheet) set; no rule, model or agent ever can.
* The comparison is written after the other items, so its check (at least two biological units
  per group) sees the groups set in the same act.

A whole 96-well plate (groups and units of 96 samples, ~190 items) records in about a second.

## What the design still needs

Above the editor, each missing item links to the control that gives it: *No reference gene yet*
→ **Choose the reference genes** (Targets); *Fewer than two groups* → **Set the groups**
(Samples); *No comparison yet* → **Choose the comparison**; proposals still waiting → **Show the
waiting proposals** (the inbox). The engine's own blockers are listed in its words.

## The sample sheet

The template (`GET /api/sessions/{sid}/design/template.csv`) has one row per sample (its name as
in the file, the design so far, its wells) and, beside it, the list of targets:

```
Sample,Group,Biological unit,Sample type,Quantity,Plate wells,,Target,Target role
S1,,,Unknown,,A1 A2 A3 A7 A8 A9,,REF,Reference
S2,,,Unknown,,A4 A5 A6 A10 A11 A12,,GOI,
```

The reader takes the samples from the `Sample` column and the target roles from every row
(rows without a sample included). A target-role column may be called Gene Type, Target type,
Target role, Reference, Housekeeping, Endogenous control or Normaliser; its values Reference,
housekeeping, ref, endogenous control (a reference gene), Target, GOI, gene of interest (a gene
of interest), Ignore (left out), or yes/no under a header that asks "is it a reference?". A
column listing reference genes by name ("Reference genes: GAPDH") works too. The rules then
propose `design.target_role` from the sheet, which outranks what the file declares (the file's
declaration is the alternative). A file that declares **every** target a reference gene (the
LightCycler 96 does) gives only Low proposals: that says nothing about which ones are.

Generic target names (`REF`, `GOI`, `target1`, `NTC`, `STD`, dye names) never get a gene-symbol
proposal, and a symbol proposed for one is never "consistent" (D-SYMBOL: cannot check).

## API

| Route | |
|---|---|
| `GET /api/sessions/{sid}/design/editor` | samples (names, declared types, wells, the type so far), each sample's group and unit (a separate list: no object holds a group next to a number), targets, groups, comparison, what is still needed and where |
| `POST /api/sessions/{sid}/design/check` | `{items}` → what recording does, with the engine's check of each; writes nothing |
| `POST /api/sessions/{sid}/design/set` | `{items, reason, expected_head, accept_contradicted}` → recorded; 409 `studio` (refused, in words), 409 `stale` (the head moved), 422 (no reason, or no `expected_head`: the editor's `head` is required) |
| `GET /api/sessions/{sid}/design/template.csv` | the pre-filled sample sheet |
| `POST /api/sessions/{sid}/sheet` | attach a sample sheet (multipart `sheet`); the rules propose again (a job) |

Code: `qpilot/studio_design.py` (plan, set, state, template), `qpilot/web/routers/design.py`,
`qpilot/web/contract_design.py`, `frontend/src/features/design/` (DesignEditor and its panels).
Tests: `tests/web/test_design_editor.py` (a CFX export + group sheet to Results with no model;
the LightCycler 96 hmuY file with its empty channel left out; a 96-well plate in one act),
`tests/engine/test_design_target_roles.py`, `frontend/src/features/design/editor.test.tsx`.
