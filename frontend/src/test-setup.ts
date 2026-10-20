// Test-wide settings. The machine running the suite may be busy (many builds at once): give
// findBy* queries and tests room, so a slow render is not mistaken for a missing element.
import { configure } from "@testing-library/react";

configure({ asyncUtilTimeout: 5000 });
