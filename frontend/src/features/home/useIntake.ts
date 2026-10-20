/** The files chosen on the Open screen, lifted to the page so a drop anywhere lands here. */
import { useState } from "react";
import { RDML_SUFFIXES, SHEET_SUFFIXES, sortFiles } from "./workspace";

/** The files chosen so far, shared with the page so a drop anywhere on it lands here. */
export interface Intake {
  rdml: File | null;
  sheet: File | null;
  sentence: string;
  /** What the last drop or choice could not use, in words. */
  notice: string | null;
  setSentence: (s: string) => void;
  add: (files: readonly File[]) => void;
  removeRdml: () => void;
  removeSheet: () => void;
  reset: () => void;
}

/** The intake's state (lifted to the page so the whole page is a drop target). */
export function useIntake(): Intake {
  const [rdml, setRdml] = useState<File | null>(null);
  const [sheet, setSheet] = useState<File | null>(null);
  const [sentence, setSentence] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  return {
    rdml,
    sheet,
    sentence,
    notice,
    setSentence,
    add: (files) => {
      const sorted = sortFiles(files);
      if (sorted.rdml) setRdml(sorted.rdml);
      if (sorted.sheet) setSheet(sorted.sheet);
      if (sorted.ignored.length) {
        const names = sorted.ignored.map((f) => f.name).join(", ");
        setNotice(
          `Not used: ${names}. qPilot opens an RDML file (${RDML_SUFFIXES.join(" or ")}) and an optional sample sheet (${SHEET_SUFFIXES.join(" or ")}).`,
        );
      } else setNotice(null);
    },
    removeRdml: () => setRdml(null),
    removeSheet: () => setSheet(null),
    reset: () => {
      setRdml(null);
      setSheet(null);
      setSentence("");
      setNotice(null);
    },
  };
}
