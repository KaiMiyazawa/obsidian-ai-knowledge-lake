#!/usr/bin/env node

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import fs from "fs";
import { google, tasks_v1 } from "googleapis";
import path from "path";
import { fileURLToPath } from "url";
import { OAuth2Client } from "google-auth-library";
import { TaskActions, TaskResources } from "./Tasks.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Env-var auth (Smithery / Claude Desktop)
const CLIENT_ID = process.env.GOOGLE_CLIENT_ID;
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET;
const REFRESH_TOKEN = process.env.GOOGLE_REFRESH_TOKEN;

// File-based auth (shared with other Google MCP servers)
const CREDENTIALS_PATH =
  process.env.GTASKS_CREDENTIALS_PATH ||
  process.env.GOOGLE_OAUTH_KEYS_PATH ||
  path.join(__dirname, "../gcp-oauth.keys.json");
const TOKEN_PATH =
  process.env.GTASKS_TOKEN_PATH ||
  process.env.GOOGLE_TASKS_CREDENTIALS_PATH ||
  path.join(__dirname, "../.gtasks-server-credentials.json");

const REDIRECT_URI = "http://localhost";
const REQUIRED_SCOPES = ["https://www.googleapis.com/auth/tasks"];

const homeDir = process.env.HOME || process.env.USERPROFILE || "";
const localConfigPath = path.join(homeDir, ".gtasks-credentials.json");

console.error("=== GTASKS MCP CONFIG ===");
console.error(
  `Env auth: CLIENT_ID=${Boolean(CLIENT_ID)} CLIENT_SECRET=${Boolean(
    CLIENT_SECRET
  )} REFRESH_TOKEN=${Boolean(REFRESH_TOKEN)}`
);
console.error(`CREDENTIALS_PATH: ${CREDENTIALS_PATH}`);
console.error(`TOKEN_PATH: ${TOKEN_PATH}`);
console.error(`Local config: ${localConfigPath} (exists=${fs.existsSync(localConfigPath)})`);
console.error("=== END CONFIG ===");

let oauth2Client: OAuth2Client | null = null;
let tasks: tasks_v1.Tasks | null = null;
let isAuthenticated = false;

const server = new Server(
  {
    name: "gtasks-mcp",
    version: "0.2.0",
  },
  {
    capabilities: {
      resources: {},
      tools: {},
    },
  }
);

function saveTokens(tokens: Record<string, unknown>) {
  try {
    let existingTokens: Record<string, unknown> = {};
    if (fs.existsSync(TOKEN_PATH)) {
      existingTokens = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf-8"));
    }
    const mergedTokens = { ...existingTokens, ...tokens };
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(mergedTokens, null, 2));
    console.error("Tokens saved to file");
  } catch (error) {
    console.error("Error saving tokens:", error);
  }
}

function attachTokenListener(client: OAuth2Client) {
  client.on("tokens", (tokens) => {
    console.error("Received new tokens, saving...");
    saveTokens(tokens as Record<string, unknown>);
  });
}

async function initializeAuth() {
  if (isAuthenticated) return true;

  try {
    // 1. Environment variables (Smithery / Claude Desktop)
    if (CLIENT_ID && CLIENT_SECRET && REFRESH_TOKEN) {
      console.error("Using credentials from environment variables");
      oauth2Client = new OAuth2Client(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI);
      oauth2Client.setCredentials({ refresh_token: REFRESH_TOKEN });
      attachTokenListener(oauth2Client);
    }
    // 2. File-based OAuth client + token files
    else if (fs.existsSync(CREDENTIALS_PATH) && fs.existsSync(TOKEN_PATH)) {
      console.error("Using credentials from GTASKS credential/token files");
      const credentialsContent = JSON.parse(
        fs.readFileSync(CREDENTIALS_PATH, "utf-8")
      );
      const credentials =
        credentialsContent.installed ||
        credentialsContent.web ||
        credentialsContent;

      if (!credentials.client_id || !credentials.client_secret) {
        console.error("Invalid credentials file format");
        return false;
      }

      oauth2Client = new OAuth2Client(
        credentials.client_id,
        credentials.client_secret,
        REDIRECT_URI
      );
      attachTokenListener(oauth2Client);

      const tokens = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf-8"));
      // Support both google-auth-library tokens and gemini-style token files
      oauth2Client.setCredentials({
        refresh_token: tokens.refresh_token,
        access_token: tokens.access_token || tokens.token,
        expiry_date: tokens.expiry_date || tokens.expiry,
        token_type: tokens.token_type,
        scope: tokens.scope || (Array.isArray(tokens.scopes) ? tokens.scopes.join(" ") : undefined),
      });
      console.error("Loaded tokens from file");
    }
    // 3. Home directory config
    else if (fs.existsSync(localConfigPath)) {
      console.error("Using credentials from local config file");
      const localConfig = JSON.parse(fs.readFileSync(localConfigPath, "utf-8"));
      oauth2Client = new OAuth2Client(
        localConfig.clientId || localConfig.client_id,
        localConfig.clientSecret || localConfig.client_secret,
        REDIRECT_URI
      );
      oauth2Client.setCredentials({
        refresh_token: localConfig.refreshToken || localConfig.refresh_token,
      });
      attachTokenListener(oauth2Client);
    }
    // 4. Token file only (legacy package credentials)
    else if (fs.existsSync(TOKEN_PATH)) {
      console.error("Using credentials from package credentials file");
      const credentials = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf-8"));
      // If the token file itself embeds client credentials, use them
      if (credentials.client_id && credentials.client_secret) {
        oauth2Client = new OAuth2Client(
          credentials.client_id,
          credentials.client_secret,
          REDIRECT_URI
        );
      } else if (fs.existsSync(CREDENTIALS_PATH)) {
        const credentialsContent = JSON.parse(
          fs.readFileSync(CREDENTIALS_PATH, "utf-8")
        );
        const clientCreds =
          credentialsContent.installed || credentialsContent.web;
        oauth2Client = new OAuth2Client(
          clientCreds.client_id,
          clientCreds.client_secret,
          REDIRECT_URI
        );
      } else {
        oauth2Client = new OAuth2Client();
      }
      oauth2Client.setCredentials(credentials);
      attachTokenListener(oauth2Client);
    } else {
      console.error(
        "Credentials not found. Please either:\n" +
          "1. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN\n" +
          "2. Set GTASKS_CREDENTIALS_PATH and GTASKS_TOKEN_PATH, then run auth\n" +
          "3. Create ~/.gtasks-credentials.json with clientId, clientSecret, refreshToken\n" +
          "4. Run with 'auth' argument after placing gcp-oauth.keys.json in the project root"
      );
      return false;
    }

    tasks = google.tasks({ version: "v1", auth: oauth2Client });
    isAuthenticated = true;
    return true;
  } catch (error) {
    console.error("Authentication error:", error);
    return false;
  }
}

server.setRequestHandler(ListResourcesRequestSchema, async (request) => {
  if (!(await initializeAuth())) {
    return {
      resources: [],
    };
  }

  const [allTasks, nextPageToken] = await TaskResources.list(request, tasks!);
  const result: {
    resources: Array<{ uri: string; mimeType: string; name: string | null | undefined }>;
    nextCursor?: string;
  } = {
    resources: allTasks.map((task) => ({
      uri: `gtasks:///${task.id}`,
      mimeType: "text/plain",
      name: task.title,
    })),
  };
  // MCP SDK expects nextCursor to be a string or omitted — never null
  if (nextPageToken) {
    result.nextCursor = nextPageToken;
  }
  return result;
});

server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  if (!(await initializeAuth())) {
    return {
      contents: [
        {
          uri: request.params.uri,
          mimeType: "text/plain",
          text: "Authentication required. Please configure Google Tasks credentials.",
        },
      ],
    };
  }

  const task = await TaskResources.read(request, tasks!);

  const taskDetails = [
    `Title: ${task.title || "No title"}`,
    `Status: ${task.status || "Unknown"}`,
    `Due: ${task.due || "Not set"}`,
    `Notes: ${task.notes || "No notes"}`,
    `Hidden: ${task.hidden || "Unknown"}`,
    `Parent: ${task.parent || "Unknown"}`,
    `Deleted?: ${task.deleted || "Unknown"}`,
    `Completed Date: ${task.completed || "Unknown"}`,
    `Position: ${task.position || "Unknown"}`,
    `ETag: ${task.etag || "Unknown"}`,
    `Links: ${task.links || "Unknown"}`,
    `Kind: ${task.kind || "Unknown"}`,
    `Created: ${task.updated || "Unknown"}`,
    `Updated: ${task.updated || "Unknown"}`,
  ].join("\n");

  return {
    contents: [
      {
        uri: request.params.uri,
        mimeType: "text/plain",
        text: taskDetails,
      },
    ],
  };
});

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "search",
        description: "Search for a task in Google Tasks",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Search query",
            },
            taskListId: {
              type: "string",
              description:
                "Task list ID to search within. If omitted, searches all lists.",
            },
            showCompleted: {
              type: "boolean",
              description: "Include completed tasks. Default: true.",
            },
            showHidden: {
              type: "boolean",
              description:
                "Include hidden tasks. Tasks completed in the Google Tasks UI are hidden, so set true to see them. Default: false.",
            },
            showDeleted: {
              type: "boolean",
              description: "Include deleted tasks. Default: false.",
            },
            showAssigned: {
              type: "boolean",
              description:
                "Include tasks assigned from Docs / Chat Spaces. Default: false.",
            },
            dueMin: {
              type: "string",
              description: "Lower bound for due date (YYYY-MM-DD or RFC 3339).",
            },
            dueMax: {
              type: "string",
              description: "Upper bound for due date (YYYY-MM-DD or RFC 3339).",
            },
            completedMin: {
              type: "string",
              description: "Lower bound for completion date (RFC 3339).",
            },
            completedMax: {
              type: "string",
              description: "Upper bound for completion date (RFC 3339).",
            },
            updatedMin: {
              type: "string",
              description: "Only tasks updated at or after this time (RFC 3339).",
            },
          },
          required: ["query"],
        },
      },
      {
        name: "list",
        description: "List all tasks in Google Tasks",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description:
                "Task list ID to list tasks from. If omitted, lists tasks from all lists.",
            },
            showCompleted: {
              type: "boolean",
              description: "Include completed tasks. Default: true.",
            },
            showHidden: {
              type: "boolean",
              description:
                "Include hidden tasks. Tasks completed in the Google Tasks UI are hidden, so set true to see them. Default: false.",
            },
            showDeleted: {
              type: "boolean",
              description: "Include deleted tasks. Default: false.",
            },
            showAssigned: {
              type: "boolean",
              description:
                "Include tasks assigned from Docs / Chat Spaces. Default: false.",
            },
            dueMin: {
              type: "string",
              description: "Lower bound for due date (YYYY-MM-DD or RFC 3339).",
            },
            dueMax: {
              type: "string",
              description: "Upper bound for due date (YYYY-MM-DD or RFC 3339).",
            },
            completedMin: {
              type: "string",
              description: "Lower bound for completion date (RFC 3339).",
            },
            completedMax: {
              type: "string",
              description: "Upper bound for completion date (RFC 3339).",
            },
            updatedMin: {
              type: "string",
              description: "Only tasks updated at or after this time (RFC 3339).",
            },
          },
        },
      },
      {
        name: "list_task_lists",
        description:
          "List all task lists in Google Tasks with their IDs and titles. Use this to discover list IDs before querying specific lists.",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "list_with_tree",
        description:
          "List tasks from a specific task list in tree format (matching Google Tasks UI order). Shows parent-child hierarchy with indentation, sorted by position.",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description:
                "Task list ID (required). Use list_task_lists to discover IDs.",
            },
            showCompleted: {
              type: "boolean",
              description: "Include completed tasks. Default: false.",
            },
            showHidden: {
              type: "boolean",
              description: "Include hidden tasks. Default: false.",
            },
          },
          required: ["taskListId"],
        },
      },
      {
        name: "move",
        description:
          "Move a task to a new position within its list or to a different list. Can reorder, indent (make subtask), or un-indent.",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description: "Source task list ID",
            },
            taskId: {
              type: "string",
              description: "Task ID to move",
            },
            parent: {
              type: "string",
              description:
                "New parent task ID (makes this task a subtask). Omit to move to top level.",
            },
            previous: {
              type: "string",
              description:
                "Task ID to position after (among siblings). Omit to place first.",
            },
            destinationTasklist: {
              type: "string",
              description:
                "Destination task list ID to move the task to a different list. Omit to stay in current list.",
            },
          },
          required: ["taskListId", "taskId"],
        },
      },
      {
        name: "create",
        description: "Create a new task in Google Tasks",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description: "Task list ID",
            },
            title: {
              type: "string",
              description: "Task title",
            },
            notes: {
              type: "string",
              description: "Task notes",
            },
            due: {
              type: "string",
              description:
                "Due date (YYYY-MM-DD or ISO 8601). The Tasks API stores the date only; any time of day is discarded.",
            },
            status: {
              type: "string",
              enum: ["needsAction", "completed"],
              description: "Initial status. Default: needsAction.",
            },
            completed: {
              type: "string",
              description: "Completion time (RFC 3339) when status is completed.",
            },
            parent: {
              type: "string",
              description: "Parent task ID (creates a subtask).",
            },
            previous: {
              type: "string",
              description: "Sibling task ID to insert after. Omit to place first.",
            },
          },
          required: ["title"],
        },
      },
      {
        name: "clear",
        description: "Clear completed tasks from a Google Tasks task list",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description: "Task list ID",
            },
          },
          required: ["taskListId"],
        },
      },
      {
        name: "delete",
        description: "Delete a task in Google Tasks",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description: "Task list ID",
            },
            id: {
              type: "string",
              description: "Task id",
            },
          },
          required: ["id", "taskListId"],
        },
      },
      {
        name: "update",
        description: "Update a task in Google Tasks",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description: "Task list ID",
            },
            id: {
              type: "string",
              description: "Task ID",
            },
            uri: {
              type: "string",
              description: "Task URI (optional, kept for compatibility)",
            },
            title: {
              type: "string",
              description: "Task title",
            },
            notes: {
              type: "string",
              description: "Task notes",
            },
            status: {
              type: "string",
              enum: ["needsAction", "completed"],
              description: "Task status (needsAction or completed)",
            },
            due: {
              type: "string",
              description:
                "Due date (YYYY-MM-DD or ISO 8601). The Tasks API stores the date only; any time of day is discarded. Changing due also erases a time of day set in the Google Tasks UI. Empty string clears the due date.",
            },
            completed: {
              type: "string",
              description:
                "Completion time (RFC 3339). Empty string clears it.",
            },
            deleted: {
              type: "boolean",
              description: "Set false to restore a deleted task.",
            },
          },
          required: ["id"],
        },
      },
      {
        name: "get",
        description:
          "Get one task by ID, including its Google Tasks web link (web:).",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: {
              type: "string",
              description: "Task list ID. Default: @default.",
            },
            id: { type: "string", description: "Task ID" },
          },
          required: ["id"],
        },
      },
      {
        name: "get_task_list",
        description: "Get one task list by ID.",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: { type: "string", description: "Task list ID" },
          },
          required: ["taskListId"],
        },
      },
      {
        name: "create_task_list",
        description: "Create a new task list.",
        inputSchema: {
          type: "object",
          properties: {
            title: { type: "string", description: "Task list title" },
          },
          required: ["title"],
        },
      },
      {
        name: "update_task_list",
        description: "Rename a task list.",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: { type: "string", description: "Task list ID" },
            title: { type: "string", description: "New title" },
          },
          required: ["taskListId", "title"],
        },
      },
      {
        name: "delete_task_list",
        description: "Delete a task list and all of its tasks.",
        inputSchema: {
          type: "object",
          properties: {
            taskListId: { type: "string", description: "Task list ID" },
          },
          required: ["taskListId"],
        },
      },
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    if (!(await initializeAuth())) {
      return {
        content: [
          {
            type: "text",
            text: "Authentication required. Please configure Google Tasks credentials.",
          },
        ],
        isError: true,
      };
    }

    if (request.params.name === "search") {
      return await TaskActions.search(request, tasks!);
    }
    if (request.params.name === "list") {
      return await TaskActions.list(request, tasks!);
    }
    if (request.params.name === "list_task_lists") {
      return await TaskActions.listTaskLists(request, tasks!);
    }
    if (request.params.name === "list_with_tree") {
      return await TaskActions.listWithTree(request, tasks!);
    }
    if (request.params.name === "move") {
      return await TaskActions.move(request, tasks!);
    }
    if (request.params.name === "create") {
      return await TaskActions.create(request, tasks!);
    }
    if (request.params.name === "update") {
      return await TaskActions.update(request, tasks!);
    }
    if (request.params.name === "delete") {
      return await TaskActions.delete(request, tasks!);
    }
    if (request.params.name === "clear") {
      return await TaskActions.clear(request, tasks!);
    }
    if (request.params.name === "get") {
      return await TaskActions.get(request, tasks!);
    }
    if (request.params.name === "get_task_list") {
      return await TaskActions.getTaskList(request, tasks!);
    }
    if (request.params.name === "create_task_list") {
      return await TaskActions.createTaskList(request, tasks!);
    }
    if (request.params.name === "update_task_list") {
      return await TaskActions.updateTaskList(request, tasks!);
    }
    if (request.params.name === "delete_task_list") {
      return await TaskActions.deleteTaskList(request, tasks!);
    }
    throw new Error("Tool not found");
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: `Error: ${
            error instanceof Error ? error.message : String(error)
          }`,
        },
      ],
      isError: true,
    };
  }
});

async function authenticateAndSaveCredentials() {
  if (!fs.existsSync(CREDENTIALS_PATH)) {
    console.error(
      `OAuth keys not found at ${CREDENTIALS_PATH}.\n` +
        "Place gcp-oauth.keys.json in the project root, or set GTASKS_CREDENTIALS_PATH / GOOGLE_OAUTH_KEYS_PATH."
    );
    process.exit(1);
  }

  console.log("Launching auth flow...");
  console.log(`Using credentials from: ${CREDENTIALS_PATH}`);
  console.log(`Will save tokens to: ${TOKEN_PATH}`);

  const { authenticate } = await import("@google-cloud/local-auth");
  const auth = await authenticate({
    keyfilePath: CREDENTIALS_PATH,
    scopes: REQUIRED_SCOPES,
  });

  fs.writeFileSync(TOKEN_PATH, JSON.stringify(auth.credentials, null, 2));
  console.log(`Tokens saved to: ${TOKEN_PATH}`);
  console.log("You can now run the server.");
}

async function initializeAndRunServer() {
  if (process.argv[2] === "auth") {
    await authenticateAndSaveCredentials().catch(console.error);
    return;
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Google Tasks MCP Server running on stdio");
}

initializeAndRunServer().catch((error) => {
  console.error("Fatal error running server:", error);
  process.exit(1);
});
