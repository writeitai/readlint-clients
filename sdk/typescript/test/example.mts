import { Readlint, ReadlintError, type Evaluation } from "@writeitai/readlint";

const client = new Readlint();
try {
  const result: Evaluation = await client.evaluate("# Article\n\nUseful text.", {
    idempotencyKey: "article-2026-11-26-v1",
    title: "An example",
    description: "For new readers",
  });
  console.log(result.id, result.report?.prose_blocks);
  const page = await client.listEvaluations({limit: 10});
  console.log(page.items.map(item => item.id));
  console.log((await client.getEvaluation(result.id)).status);
  await client.deleteEvaluation(result.id);
} catch (error) {
  if (error instanceof ReadlintError) console.error(error.code, error.status, error.message);
  else throw error;
}
