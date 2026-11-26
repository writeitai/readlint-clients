import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: process.env.READLINT_OPENAPI_INPUT ?? "../../contracts/openapi.json",
  output: { path: process.env.READLINT_OPENAPI_OUTPUT ?? "./src/gen" },
  plugins: ["@hey-api/typescript"],
});
