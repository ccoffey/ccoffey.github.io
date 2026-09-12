import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: ["_site/**", "test-results/**"],
  },
  {
    files: ["js/**/*.js"],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: globals.browser,
    },
  },
  {
    files: [".lint-tmp/**/*.js"],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: {
        ...globals.browser,
        TEMPLATE_VALUE: "readonly",
        gtag: "readonly",
      },
    },
    // Event handlers are referenced from template attributes, so ESLint sees
    // them as unused after extraction even though they are public globals.
    rules: {
      ...js.configs.recommended.rules,
      "no-unused-vars": "off",
    },
  },
];
