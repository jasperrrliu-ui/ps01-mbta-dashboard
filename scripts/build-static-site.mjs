import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const dist = path.join(root, "dist");

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });

for (const entry of ["index.html", "assets", ".openai"]) {
  await cp(path.join(root, entry), path.join(dist, entry), { recursive: true });
}

await mkdir(path.join(dist, "data"), { recursive: true });
await cp(path.join(root, "data", "processed"), path.join(dist, "data", "processed"), { recursive: true });
await mkdir(path.join(dist, "data", "analysis"), { recursive: true });
await cp(path.join(root, "data", "analysis", "commute-hour-comparison.xlsx"), path.join(dist, "data", "analysis", "commute-hour-comparison.xlsx"));
await cp(path.join(root, "deliverables"), path.join(dist, "deliverables"), { recursive: true });
