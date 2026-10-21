/** The online demo's links and sentences (the banner, refusals, the Open card). */

// Links a visitor may follow from the demo page (navigation, never a request the page makes).
// eslint-disable-next-line no-restricted-syntax
export const GITHUB = "https://github.com/ShivaTeja05/Qpilot";
export const QUICKSTART = `${GITHUB}#quickstart`;

export const STUDY =
  "the public Vermeulen 2013 neuroblastoma study (Vermeulen et al. 2009, Ruijter et al. 2013; CC BY 4.0)";

export const READ_ONLY = `This online demo is read-only. Install qPilot to analyse your own files: ${QUICKSTART}`;

export const NOT_RECORDED = `This online demo answers what was recorded from qPilot on ${STUDY}, and this was not part of the recording. Install qPilot to try anything on your own data: ${QUICKSTART}`;

/** Error panels' headings for the demo's own refusals. */
export const DEMO_HEADING: Record<string, string> = {
  read_only: "Read-only online demo",
  not_recorded: "Not in the online demo",
};
