#!/usr/bin/env node
/**
 * End-to-end smoke test against a live Google Tasks account.
 *
 * Auth (first match wins):
 *   GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN
 *   GTASKS_CREDENTIALS_PATH + GTASKS_TOKEN_PATH
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const marker = `[e2e-${Date.now()}]`;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function callTool(client, name, args = {}) {
  const result = await client.callTool({ name, arguments: args });
  const text = (result.content || [])
    .filter((c) => c.type === "text")
    .map((c) => c.text)
    .join("\n");
  if (result.isError) {
    throw new Error(`Tool ${name} failed: ${text}`);
  }
  return text;
}

async function main() {
  const env = { ...process.env };
  const hasEnvAuth =
    env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET && env.GOOGLE_REFRESH_TOKEN;
  const hasFileAuth = env.GTASKS_CREDENTIALS_PATH && env.GTASKS_TOKEN_PATH;
  if (!hasEnvAuth && !hasFileAuth) {
    throw new Error(
      "Set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REFRESH_TOKEN or GTASKS_CREDENTIALS_PATH/GTASKS_TOKEN_PATH before running e2e"
    );
  }

  const transport = new StdioClientTransport({
    command: "node",
    args: [path.join(root, "dist/index.js")],
    env,
    stderr: "pipe",
  });

  transport.stderr?.on("data", (chunk) => {
    process.stderr.write(chunk);
  });

  const client = new Client(
    { name: "gtasks-e2e", version: "0.2.0" },
    { capabilities: {} }
  );

  await client.connect(transport);
  console.log("Connected to MCP server");

  const tools = await client.listTools();
  const toolNames = tools.tools.map((t) => t.name).sort();
  console.log("Tools:", toolNames.join(", "));
  for (const required of [
    "search",
    "list",
    "list_task_lists",
    "list_with_tree",
    "move",
    "create",
    "update",
    "delete",
    "clear",
  ]) {
    assert(toolNames.includes(required), `Missing tool: ${required}`);
  }

  const listsText = await callTool(client, "list_task_lists");
  console.log(listsText);
  const listIdMatch = listsText.match(/id:([^\s|]+)/);
  assert(listIdMatch, "Could not parse a task list id");
  const taskListId = listIdMatch[1];

  const createText = await callTool(client, "create", {
    taskListId,
    title: `${marker} parent`,
    notes: "e2e parent task",
    due: "2026-07-25",
  });
  console.log(createText);
  assert(createText.includes("Task created"), "create parent failed");

  const createChildText = await callTool(client, "create", {
    taskListId,
    title: `${marker} child`,
    notes: "e2e child task",
  });
  console.log(createChildText);

  const listText = await callTool(client, "list", { taskListId });
  assert(listText.includes(`${marker} parent`), "list missing parent");
  assert(listText.includes(`${marker} child`), "list missing child");

  const escapeRegExp = (value) =>
    value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parentId = listText.match(
    new RegExp(`${escapeRegExp(marker)} parent[\\s\\S]*?ID: ([^\\s]+)`)
  )?.[1];
  const childId = listText.match(
    new RegExp(`${escapeRegExp(marker)} child[\\s\\S]*?ID: ([^\\s]+)`)
  )?.[1];
  assert(parentId && childId, "Could not parse created task ids");
  console.log("parentId=", parentId, "childId=", childId);

  const searchText = await callTool(client, "search", {
    query: marker,
    taskListId,
  });
  assert(
    searchText.includes("Found 2 tasks"),
    `search count wrong: ${searchText.split("\n")[0]}`
  );

  const moveText = await callTool(client, "move", {
    taskListId,
    taskId: childId,
    parent: parentId,
  });
  console.log(moveText);
  assert(moveText.includes("Task moved"), "move failed");

  const treeText = await callTool(client, "list_with_tree", {
    taskListId,
    showCompleted: true,
  });
  console.log(treeText);
  assert(treeText.includes(`${marker} parent`), "tree missing parent");
  assert(treeText.includes(`${marker} child`), "tree missing child");
  assert(treeText.includes(`parent:${parentId}`), "tree missing parent link");

  const updateText = await callTool(client, "update", {
    taskListId,
    id: parentId,
    status: "completed",
  });
  console.log(updateText);
  assert(updateText.includes("Task updated"), "update failed");

  // Cleanup: delete child then parent
  console.log(await callTool(client, "delete", { taskListId, id: childId }));
  console.log(await callTool(client, "delete", { taskListId, id: parentId }));

  const after = await callTool(client, "search", {
    query: marker,
    taskListId,
  });
  assert(
    after.includes("Found 0 tasks"),
    `cleanup incomplete: ${after.split("\n")[0]}`
  );

  await client.close();
  console.log("\nE2E passed");
}

main().catch((error) => {
  console.error("\nE2E failed:", error);
  process.exit(1);
});
