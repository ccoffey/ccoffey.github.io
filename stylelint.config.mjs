export default {
  extends: ["stylelint-config-standard"],
  ignoreFiles: ["_site/**", "test-results/**"],
  rules: {
    // Keep the existing compact CSS style while enforcing semantic and syntax
    // mistakes. These rules are formatting or notation preferences, not bugs.
    "alpha-value-notation": null,
    "at-rule-empty-line-before": null,
    "color-function-alias-notation": null,
    "color-function-notation": null,
    "color-hex-length": null,
    "declaration-block-single-line-max-declarations": null,
    "media-feature-range-notation": null,
    "no-descending-specificity": null,
    "property-no-vendor-prefix": null,
    "rule-empty-line-before": null,
    "shorthand-property-no-redundant-values": null,
  },
};
