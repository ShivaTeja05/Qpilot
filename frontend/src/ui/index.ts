/**
 * qPilot's UI kit. Import from `@/ui`. Tokens only (no raw hex), keyboard and focus built in,
 * light + dark. Numbers go through `@/lib/format`; engine words through `@/lib/vocab`.
 *
 * Buttons
 *   Button          variant primary|secondary|ghost|danger|link · size sm|md|lg · loading · icon · asChild
 *   IconButton      square icon-only button; `label` (required) is its accessible name
 * Surfaces & layout
 *   Card            rounded-xl bordered surface (`as` div|section|article|li)
 *   CardHeader      title · hint · actions row at the top of a Card (level 2|3)
 *   CardBody        padded card content
 *   PageHeader      a section's h1 + one-line hint + actions (+ eyebrow)
 *   SectionTitle    h2 inside a page with hint and actions
 *   KeyValues       label/value rows: rows=[[label, value], …]
 * Labels & tags
 *   Badge           tone neutral|accent|ok|warn|danger|info · icon
 *   Kbd             a keyboard key
 *   Dot             status dot: tone · label (screen readers) · pulse
 *   ConclusionTag   ▲ up / ▼ down / — no call: conclusion · compact · long
 *   LevelTag        High/Moderate/Low/Very low with 4/3/2/1 bars: level · hideWord
 *   LevelBars       the bars alone: level
 *   VerdictTag      the six audit verdicts, glyph + word: verdict · compact
 *   Glyph           a Mark ({shape, tone}) as an inline icon: mark · size  (VERDICT[v], LEVEL[l], CONCLUSION[c])
 *   GlyphMark       a Mark inside a chart's SVG at (x, y): mark · x · y · r · ring
 *   ShapeBody       the raw shape centred on (0, 0) inside an <svg>: shape · tone · r · ring
 *   ShapeGlyph      a bare Shape inline in currentColor: shape · size · tone
 *   CheckTag        engine check consistent|contradicted|cannot_check
 * Overlays
 *   Dialog          modal: open · onOpenChange · trigger · title · description · footer · size sm|md|lg|xl
 *   DialogClose     wraps a button that closes the dialog (asChild)
 *   Sheet           drawer: open · onOpenChange · title · side right|left|bottom · width · footer · actions · modal · offsetTop
 *   Popover         trigger · children · align · side · label
 *   PopoverClose    closes the popover (asChild)
 *   Tooltip         content · children (one focusable child) · side
 *   TooltipProvider mounted once by the shell
 *   Menu, MenuTrigger, MenuContent, MenuItem (icon · shortcut · danger), MenuLabel, MenuSeparator
 * Controls
 *   Field           label · hint · error · optional · htmlFor around a control
 *   Input           text input (forwardRef)
 *   Textarea        text box; `maxLength` + `showCount` shows a live "n / max" counter
 *   Select          value · onValueChange · options [{value,label,hint}] · placeholder · label · size
 *   Switch          checked · onCheckedChange · label · hint
 *   SegmentedControl value · onValueChange · options [{value,label}] · label (group name) · size
 *   Tabs, TabsList (label), TabsTrigger (value · count), TabsContent (value)
 * Tables
 *   Table, THead, TBody, TR, TH (numeric), TD (numeric)   semantic dense table primitives
 *   NumberCell      mono tabular number content · muted
 *   DataTable       virtualised sortable table: data · columns (TanStack ColumnDef, meta: ColumnMeta)
 *                   · getRowId · label · height · rowHeight · initialSorting · globalFilter · rowFilter
 *                   · onRowClick · selectedId · empty
 * States
 *   Skeleton        shimmer block (className sets size)
 *   LoadingBlock    a few skeleton lines + "Loading…" for screen readers: label · lines
 *   EmptyState      icon · title · children (what to do) · action · compact
 *   ProgressBar     value 0–1 (indeterminate when null) · label
 *   ErrorPanel      error (ApiError aware: needsKey / stale / offline) · title · onRetry · compact
 *   errorMessage    an error's plain words; errorHeading: a heading from its code
 *   TickText        text with `backticks` shown as code (server messages): text
 *   JobCard         id (followed with useJob) or job · children(result, job) once done · onDismiss
 * Copy
 *   CopyButton      text · label · showLabel · size
 *   Hash            short mono hash, click copies the full value: value · length · prefix
 *   CommandLine     a mono command with a copy button: command
 * Toasts
 *   Toaster         mounted once by the shell
 *   toast           sonner's toast (success/error/info/warning, action: {label, onClick})
 */
import "./ui.css";

export {
  Button,
  IconButton,
  type ButtonProps,
  type ButtonSize,
  type ButtonVariant,
  type IconButtonProps,
} from "./Button";
export { Card, CardBody, CardHeader, KeyValues, PageHeader, SectionTitle } from "./Card";
export { Badge, Dot, Kbd, type Tone } from "./Badge";
export { CheckTag, ConclusionTag, LevelBars, LevelTag, VerdictTag } from "./tags";
export { Glyph, GlyphMark, ShapeBody, ShapeGlyph, type ShapeBodyProps } from "./Glyph";
export {
  Dialog,
  DialogClose,
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
  Popover,
  PopoverClose,
  Sheet,
  Tooltip,
  TooltipProvider,
  type DialogProps,
  type SheetProps,
} from "./overlay";
export {
  Field,
  Input,
  SegmentedControl,
  Select,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  type SelectOption,
  type TextareaProps,
} from "./controls";
export {
  DataTable,
  NumberCell,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  type ColumnDef,
  type ColumnMeta,
  type DataTableProps,
  type SortingState,
} from "./Table";
export { EmptyState, LoadingBlock, ProgressBar, Skeleton } from "./feedback";
export { ErrorPanel, TickText, errorHeading, errorMessage } from "./ErrorPanel";
export { JobCard } from "./JobCard";
export { CommandLine, CopyButton, Hash } from "./Copy";
export { Toaster, toast } from "./Toaster";
