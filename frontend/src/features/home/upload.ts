/**
 * Opening a file: `POST /api/workspaces` as a multipart form, with upload progress (fetch has
 * none, so this one request uses XMLHttpRequest). Errors come back as {@link ApiError} in the
 * server's own words, like every other request.
 */
import { ApiError, type Schemas } from "@/api/client";

export interface UploadProgress {
  loaded: number;
  total: number;
}

export interface OpenFileInput {
  rdml: File;
  sheet?: File | null;
  sentence?: string;
}

interface ErrorShape {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
}

const OFFLINE = "qPilot is not answering. Is `qpilot app` still running?";

/** Start opening a file; resolves with the open job once the upload is in. `abort()` cancels it. */
export function openFile(
  input: OpenFileInput,
  onProgress: (p: UploadProgress) => void,
): { done: Promise<Schemas["JobStarted"]>; abort: () => void } {
  const form = new FormData();
  form.append("rdml", input.rdml, input.rdml.name);
  if (input.sheet) form.append("sheet", input.sheet, input.sheet.name);
  const sentence = input.sentence?.trim();
  if (sentence) form.append("sentence", sentence);

  const xhr = new XMLHttpRequest();
  const done = new Promise<Schemas["JobStarted"]>((resolve, reject) => {
    xhr.open("POST", "/api/workspaces");
    xhr.withCredentials = true;
    xhr.responseType = "text";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress({ loaded: e.loaded, total: e.total });
    };
    xhr.onerror = () => reject(new ApiError(0, "offline", OFFLINE));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "The upload was cancelled."));
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as Schemas["JobStarted"]);
        return;
      }
      const e = (body as ErrorShape | undefined)?.error;
      reject(
        new ApiError(
          xhr.status,
          e?.code ?? `http_${xhr.status}`,
          e?.message ?? "The server could not open this file.",
          e?.details ?? {},
        ),
      );
    };
    xhr.send(form);
  });
  return { done, abort: () => xhr.abort() };
}
