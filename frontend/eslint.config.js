import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["node_modules", "src/api/schema.d.ts", "../qpilot/web/static", "dist-demo"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "19" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Every string from the server or a file is text. Never inject HTML: React's escaping is
      // what replaces the old pages' html.escape.
      "react/no-danger": "error",
      "react/no-danger-with-children": "error",
      "react/jsx-no-target-blank": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector: "MemberExpression[property.name='innerHTML']",
          message: "Do not write HTML; render text with React.",
        },
        {
          selector: "Literal[value=/^https?:\\/\\/(?!127\\.0\\.0\\.1|localhost)/]",
          message: "The page makes no outbound request: no external URLs in code.",
        },
      ],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
