/** The files chosen on the Open screen, lifted to the page so a drop anywhere lands here. */
import { useState } from "react";
import { addFiles, planUpload, type UploadPlan } from "./workspace";

/** The files chosen so far, shared with the page so a drop anywhere on it lands here. */
export interface Intake {
  /** Every file dropped or chosen (an RDML file, an export set, a sample sheet among them). */
  files: File[];
  /** A file the person added with "Add a sample sheet". */
  sheet: File | null;
  sentence: string;
  /** What the last drop or choice could not use, in words. */
  notice: string | null;
  /** How the files will be sent (null: nothing to open yet). */
  plan: UploadPlan<File> | null;
  setSentence: (s: string) => void;
  add: (files: readonly File[]) => void;
  setSheet: (file: File | null) => void;
  remove: (file: File) => void;
  reset: () => void;
}

/** The intake's state (lifted to the page so the whole page is a drop target). */
export function useIntake(): Intake {
  const [files, setFiles] = useState<File[]>([]);
  const [sheet, setSheet] = useState<File | null>(null);
  const [sentence, setSentence] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  return {
    files,
    sheet,
    sentence,
    notice,
    plan: planUpload(files, sheet),
    setSentence,
    add: (incoming) => {
      const picked = addFiles(files, incoming);
      setFiles(picked.files);
      setNotice(picked.ignored.length ? picked.ignored.map((i) => i.reason).join(" ") : null);
    },
    setSheet: (file) => {
      setSheet(file);
      setNotice(null);
    },
    remove: (file) => setFiles((cur) => cur.filter((f) => f !== file)),
    reset: () => {
      setFiles([]);
      setSheet(null);
      setSentence("");
      setNotice(null);
    },
  };
}
