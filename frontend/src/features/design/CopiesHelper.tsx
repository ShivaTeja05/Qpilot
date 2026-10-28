/**
 * ng → copies, where standards are set: how many copies the mass of a plasmid, PCR product,
 * oligo or transcript holds (the engine's formula, `GET /api/tools/copies`), so the top quantity
 * of a dilution series can be given in copies. It reads nothing about the plate (the Design page
 * is blind): only the numbers typed here. "Use" puts the copies in the highest-quantity field.
 */
import { useQuery } from "@tanstack/react-query";
import { Calculator } from "lucide-react";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { NNBSP, fixed } from "@/lib/format";
import { Button, Input, Select } from "@/ui";

type Kind = "dsDNA" | "ssDNA" | "RNA";
const KINDS: { value: Kind; label: string; hint: string }[] = [
  { value: "dsDNA", label: "dsDNA (bp)", hint: "a plasmid, PCR product or gBlock" },
  { value: "ssDNA", label: "ssDNA (nt)", hint: "an oligo" },
  { value: "RNA", label: "RNA (nt)", hint: "an in vitro transcript" },
];
const SUP: Record<string, string> = {
  "-": "⁻",
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};

/** `3.25 × 10⁸` (three significant digits). */
export function copiesWords(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "—";
  const e = Math.floor(Math.log10(n));
  if (e < 5) return fixed(Number(n.toPrecision(3)), Math.max(0, 2 - e));
  let m = n / 10 ** e;
  let exp = e;
  if (Number(m.toPrecision(3)) >= 10) {
    m /= 10;
    exp += 1;
  }
  const power = String(exp)
    .split("")
    .map((c) => SUP[c] ?? c)
    .join("");
  return `${m.toPrecision(3)}${NNBSP}×${NNBSP}10${power}`;
}

function positive(text: string): number | null {
  const v = Number(text.trim());
  return text.trim() !== "" && Number.isFinite(v) && v > 0 ? v : null;
}

export function CopiesHelper({ onUse }: { onUse: (copies: number) => void }) {
  const [open, setOpen] = useState(false);
  const [ng, setNg] = useState("");
  const [length, setLength] = useState("");
  const [kind, setKind] = useState<Kind>("dsDNA");
  const query =
    positive(ng) && positive(length)
      ? { ng: positive(ng)!, length: positive(length)!, kind }
      : null;
  const answer = useQuery({
    queryKey: ["tools", "copies", query],
    enabled: open && query != null,
    queryFn: () => unwrap(api.GET("/api/tools/copies", { params: { query: query! } })),
    staleTime: Infinity,
    retry: false,
  });
  if (!open) {
    return (
      <Button
        size="sm"
        variant="ghost"
        icon={<Calculator aria-hidden />}
        onClick={() => setOpen(true)}
      >
        From ng to copies…
      </Button>
    );
  }
  const data = answer.data;
  return (
    <div
      className="basis-full rounded-lg border border-line bg-surface-2 p-2.5 text-xs text-muted"
      role="group"
      aria-label="ng to copies"
    >
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          ng (or ng per µL)
          <Input
            inputMode="decimal"
            className="h-7 w-24 text-[13px]"
            value={ng}
            placeholder="e.g. 1"
            onChange={(e) => setNg(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          Length
          <Input
            inputMode="decimal"
            className="h-7 w-24 text-[13px]"
            value={length}
            placeholder="e.g. 3000"
            onChange={(e) => setLength(e.target.value)}
          />
        </label>
        <div className="flex flex-col gap-1">
          <span>Molecule</span>
          <Select label="Molecule" size="sm" value={kind} onValueChange={setKind} options={KINDS} />
        </div>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>
      <p className="mt-2 text-[12.5px] text-fg" role="status" aria-live="polite">
        {query == null
          ? "Give the mass and the length to work out the copies."
          : answer.isError
            ? "These numbers cannot be converted."
            : data
              ? `${fixed(data.ng, data.ng < 1 ? 3 : 1)} ng of ${data.kind_words} ${fixed(data.length, 0)} long = ${copiesWords(data.copies)} copies (molar mass ${copiesWords(data.molar_mass)} g/mol).`
              : "Working it out…"}
      </p>
      {data && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onUse(Number(data.copies.toPrecision(4)))}
          >
            Use as the highest quantity
          </Button>
          <span className="text-faint">{data.reference}</span>
        </div>
      )}
    </div>
  );
}
