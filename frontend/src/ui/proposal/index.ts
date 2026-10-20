/**
 * The Studio proposal card, shared by Design, Curves and Prism. Import from `@/ui/proposal`.
 *
 *   ProposalCard        one proposal in six parts (proposal + alternatives · Why · Engine check ·
 *                       Consequence · Level · Accept / Edit / Reject) and who made it.
 *                       Data: proposal · quotes (text_id → QuarantineEntry) · sheetCells ·
 *                       resultsVisible · matters / mattersJob / onAskMatters · stale.
 *                       Actions (each returns a promise; throw to refuse, the card shows why):
 *                       onAccept(reason) · onEdit(edits, reason) · onReject(reason) ·
 *                       onCheckEdit(edits) → ProposalCheck (live re-check while editing).
 *                       Links: onOpenWell("run_id/well"). Inbox: focused · onFocusCard · ref
 *                       (ProposalCardHandle: accept / edit / reject / focus, for `a` `e` `x`).
 *                       Slots: children (under the proposal) · footer · renderEditor · readOnly.
 *   PayloadEditor       the edit fields of one kind of proposal (used by the card)
 *   Quote               a quoted file text with its origin and flags (instruction-like marked)
 *   EvidenceList        every source behind a proposal
 *   DetailsView         a check's or a consequence's numbers in words; wells open their curve
 *   CheckSummary, RuleChip, MattersLine, ExclusionConsequence
 *
 *   StageInbox          a stage's inbox (sid · stage · resultsVisible · onOpenWell · empty ·
 *                       allDecided · filter/onClearFilter · onFocusProposal · cardExtra · cardProps
 *                       · editOptions · hotkeys): pending first (contradicted first), filters,
 *                       j/k + a/e/x, "Decided in this stage (n)" folded underneath.
 *   BulkActions         "Accept all consistent…" and "Reject contradicted AI calls…" (sid · stage):
 *                       the exact list first, then exactly that list; off when nothing qualifies.
 *   ConfirmStage        "Confirm this stage…" (sid · stage · status): what it covers, "Yes, confirm".
 *   DecidedList, ProposalLines, BulkAction
 *   useStageProposals(sid, stage) · useQuotes(sid) → {lookup, sheetCells} ·
 *   useProposalActions(sid, head) · useMattersJobs(sid)
 *
 * The words for origins, flags, rule ids and check fields live in `./words`.
 */
export {
  MAX_REASON,
  ProposalCard,
  type ProposalAction,
  type ProposalCardHandle,
  type ProposalCardProps,
} from "./ProposalCard";
export { AlternativeStarts, PayloadEditor, diffPayload, type EditOptions, type Payload } from "./edit";
export {
  CheckSummary,
  DetailsView,
  EvidenceList,
  ExclusionConsequence,
  MattersLine,
  Quote,
  RuleChip,
  evidenceSummary,
  type ProposalCheck,
  type QuoteLookup,
} from "./parts";
export {
  FLAG_WORDS,
  RULE_WORDS,
  detailLabel,
  detailValue,
  originWords,
  visibleText,
  type QuarantineEntry,
} from "./words";
export { DecidedList, StageInbox, type InboxFilter, type StageInboxProps } from "./StageInbox";
export { BulkAction, BulkActions, ConfirmStage, ProposalLines } from "./StageActions";
export {
  useMattersJobs,
  useProposalActions,
  useQuotes,
  useStageProposals,
  type ConfirmableStage,
  type InboxStage,
} from "./hooks";
