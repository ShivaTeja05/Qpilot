/**
 * Find recorded text exactly as the server wrote it. Testing Library collapses whitespace in the
 * page but not in the string asked for, so a recorded "91 %" (narrow no-break space) would never
 * match; this keeps every space as written on both sides.
 */
import { getDefaultNormalizer } from "@testing-library/react";

export const asWritten = { normalizer: getDefaultNormalizer({ collapseWhitespace: false }) };
