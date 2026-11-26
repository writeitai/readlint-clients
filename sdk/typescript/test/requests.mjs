import { readFileSync } from "node:fs";
import * as sdk from "../dist/index.js";
import { exercise } from "./contract.mjs";
const fixtures = JSON.parse(readFileSync(new URL("../../../contracts/fixtures.json", import.meta.url)));
console.log(JSON.stringify(await exercise(sdk, fixtures)));
