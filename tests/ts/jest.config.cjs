/** Jest configuration for TypeScript package tests. */
module.exports = {
  rootDir: "../..",
  testEnvironment: "node",
  testMatch: ["<rootDir>/tests/ts/**/*.test.ts"],
  transform: {
    "^.+\\.ts$": [
      "ts-jest",
      {
        tsconfig: "<rootDir>/tests/ts/tsconfig.test.json",
        diagnostics: { warnOnly: true },
      },
    ],
  },
  moduleNameMapper: {
    "^@cqa/shared$": "<rootDir>/packages/shared/src/index.ts",
    "^@cqa/parser-core$": "<rootDir>/packages/parser-core/src/index.ts",
  },
  moduleFileExtensions: ["ts", "js", "json"],
  clearMocks: true,
};
