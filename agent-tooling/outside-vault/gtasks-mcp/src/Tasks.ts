import {
  CallToolRequest,
  ListResourcesRequest,
  ReadResourceRequest,
} from "@modelcontextprotocol/sdk/types.js";
import { GaxiosResponse } from "gaxios";
import { tasks_v1 } from "googleapis";

const MAX_TASK_RESULTS = 100;

/**
 * Normalize due dates to RFC3339 midnight UTC as required by Google Tasks.
 * Accepts: "2025-03-19", "2025-03-19T21:00:00", "2025-03-19T21:00:00Z", etc.
 */
export function normalizeDueDate(due: string | undefined): string | undefined {
  if (!due) return undefined;
  const parsed = new Date(due);
  if (isNaN(parsed.getTime())) {
    throw new Error(
      `Invalid due date format: "${due}". Use YYYY-MM-DD or ISO 8601 format.`
    );
  }
  const year = parsed.getUTCFullYear();
  const month = String(parsed.getUTCMonth() + 1).padStart(2, "0");
  const day = String(parsed.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}T00:00:00.000Z`;
}

type ListFilters = Pick<
  tasks_v1.Params$Resource$Tasks$List,
  | "dueMin"
  | "dueMax"
  | "completedMin"
  | "completedMax"
  | "updatedMin"
  | "showDeleted"
  | "showAssigned"
>;

/**
 * Convert "YYYY-MM-DD" or any ISO 8601 string to an RFC3339 timestamp.
 * Date-only input is treated as midnight UTC, matching how due dates are stored.
 */
export function toRfc3339(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(value);
  if (isNaN(parsed.getTime())) {
    throw new Error(
      `Invalid date format: "${value}". Use YYYY-MM-DD or ISO 8601 format.`
    );
  }
  return parsed.toISOString();
}

export class TaskResources {
  static async read(request: ReadResourceRequest, tasks: tasks_v1.Tasks) {
    const taskId = request.params.uri.replace("gtasks:///", "");

    const taskListsResponse: GaxiosResponse<tasks_v1.Schema$TaskLists> =
      await tasks.tasklists.list({
        maxResults: MAX_TASK_RESULTS,
      });

    const taskLists = taskListsResponse.data.items || [];
    let task: tasks_v1.Schema$Task | null = null;

    for (const taskList of taskLists) {
      if (taskList.id) {
        try {
          const taskResponse: GaxiosResponse<tasks_v1.Schema$Task> =
            await tasks.tasks.get({
              tasklist: taskList.id,
              task: taskId,
            });
          task = taskResponse.data;
          break;
        } catch (error) {
          // Task not found in this list, continue to the next one
        }
      }
    }

    if (!task) {
      throw new Error("Task not found");
    }

    return task;
  }

  static async list(
    request: ListResourcesRequest,
    tasks: tasks_v1.Tasks
  ): Promise<[tasks_v1.Schema$Task[], string | undefined]> {
    const pageSize = 10;
    const params: Record<string, unknown> = {
      maxResults: pageSize,
    };

    if (request.params?.cursor) {
      params.pageToken = request.params.cursor;
    }

    const taskListsResponse = await tasks.tasklists.list({
      maxResults: MAX_TASK_RESULTS,
    });

    const taskLists = taskListsResponse.data.items || [];

    let allTasks: tasks_v1.Schema$Task[] = [];
    let nextPageToken: string | undefined;

    for (const taskList of taskLists) {
      if (!taskList.id) continue;

      const tasksResponse = await tasks.tasks.list({
        tasklist: taskList.id,
        ...params,
      });

      const taskItems = tasksResponse.data.items || [];
      allTasks = allTasks.concat(taskItems);

      if (tasksResponse.data.nextPageToken) {
        nextPageToken = tasksResponse.data.nextPageToken;
      }
    }

    return [allTasks, nextPageToken];
  }
}

export class TaskActions {
  private static formatTask(task: tasks_v1.Schema$Task) {
    const parts = [
      task.title || "(no title)",
      `id:${task.id}`,
      `status:${task.status}`,
    ];
    if (task.due) parts.push(`due:${task.due.slice(0, 10)}`);
    if (task.completed) parts.push(`completed:${task.completed}`);
    if (task.parent) parts.push(`parent:${task.parent}`);
    if (task.hidden) parts.push("hidden");
    if (task.deleted) parts.push("deleted");
    if (task.assignmentInfo?.surfaceType)
      parts.push(`assigned:${task.assignmentInfo.surfaceType}`);
    if (task.links?.length)
      parts.push(
        `links:${task.links.map((l) => `${l.description ?? l.type}<${l.link}>`).join(",")}`
      );
    if (task.webViewLink) parts.push(`web:${task.webViewLink}`);
    const notes = task.notes ? `\n  notes: ${task.notes.replace(/\n/g, "\n  ")}` : "";
    return parts.join(" | ") + notes;
  }

  private static formatTaskList(taskList: tasks_v1.Schema$Task[]) {
    return taskList.map((task) => this.formatTask(task)).join("\n");
  }

  /**
   * Fetch all tasks from a single task list, following pagination tokens.
   */
  private static async _fetchAllTasksFromList(
    tasks: tasks_v1.Tasks,
    taskListId: string,
    showCompleted: boolean = true,
    showHidden: boolean = false,
    filters: ListFilters = {}
  ): Promise<tasks_v1.Schema$Task[]> {
    const allTasks: tasks_v1.Schema$Task[] = [];
    let pageToken: string | undefined;

    do {
      const response = await tasks.tasks.list({
        tasklist: taskListId,
        maxResults: MAX_TASK_RESULTS,
        showCompleted,
        showHidden,
        ...filters,
        ...(pageToken ? { pageToken } : {}),
      });

      const items = response.data.items || [];
      allTasks.push(...items);
      pageToken = response.data.nextPageToken ?? undefined;
    } while (pageToken);

    return allTasks;
  }

  private static _listOptions(request: CallToolRequest) {
    const args = request.params.arguments ?? {};
    const filters: ListFilters = {};
    for (const key of [
      "dueMin",
      "dueMax",
      "completedMin",
      "completedMax",
      "updatedMin",
    ] as const) {
      const value = toRfc3339(args[key] as string | undefined);
      if (value) filters[key] = value;
    }
    if (args.showDeleted !== undefined)
      filters.showDeleted = args.showDeleted as boolean;
    if (args.showAssigned !== undefined)
      filters.showAssigned = args.showAssigned as boolean;
    return {
      showCompleted: (args.showCompleted as boolean | undefined) ?? true,
      showHidden: (args.showHidden as boolean | undefined) ?? false,
      filters,
    };
  }

  private static async _list(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    const requestedTaskListId = request.params.arguments?.taskListId as
      | string
      | undefined;
    const { showCompleted, showHidden, filters } = this._listOptions(request);
    const fetchList = (id: string) =>
      this._fetchAllTasksFromList(tasks, id, showCompleted, showHidden, filters);

    // If a specific taskListId is provided, only fetch that list
    if (requestedTaskListId) {
      return fetchList(requestedTaskListId);
    }

    // Otherwise fetch all lists (backward compatible)
    const taskListsResponse = await tasks.tasklists.list({
      maxResults: MAX_TASK_RESULTS,
    });

    const taskLists = taskListsResponse.data.items || [];
    let allTasks: tasks_v1.Schema$Task[] = [];

    for (const taskList of taskLists) {
      if (taskList.id) {
        try {
          const items = await fetchList(taskList.id);
          allTasks = allTasks.concat(items);
        } catch (error) {
          console.error(`Error fetching tasks for list ${taskList.id}:`, error);
        }
      }
    }
    return allTasks;
  }

  static async create(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      // First, get available task lists to ensure we have a valid list
      const taskListsResponse = await tasks.tasklists.list({
        maxResults: MAX_TASK_RESULTS,
      });

      const taskLists = taskListsResponse.data.items || [];
      let taskListId: string;

      // If no task lists found, create a default one
      if (!taskLists.length) {
        console.error("No task lists found, creating a default task list");
        try {
          const newTaskList = await tasks.tasklists.insert({
            requestBody: {
              title: "My Tasks",
            },
          });

          if (!newTaskList.data.id) {
            throw new Error("Failed to create a new task list");
          }

          taskListId = newTaskList.data.id;
          console.error(
            `Created new task list: ${newTaskList.data.title} (${taskListId})`
          );
        } catch (error) {
          console.error("Error creating task list:", error);
          throw new Error(
            `Failed to create a task list. Make sure you have the correct permissions: ${
              error instanceof Error ? error.message : String(error)
            }`
          );
        }
      } else {
        // Use the specified task list or default to the first one
        const requestedTaskListId = request.params.arguments
          ?.taskListId as string;
        if (requestedTaskListId && requestedTaskListId !== "@default") {
          // Check if the requested task list exists
          const foundTaskList = taskLists.find(
            (list) => list.id === requestedTaskListId
          );
          if (foundTaskList) {
            taskListId = requestedTaskListId;
          } else {
            taskListId = taskLists[0].id!;
            console.error(
              `Requested task list ${requestedTaskListId} not found, using first task list: ${taskLists[0].title} (${taskListId})`
            );
          }
        } else {
          taskListId = taskLists[0].id!;
          console.error(
            `Using first task list: ${taskLists[0].title} (${taskListId})`
          );
        }
      }

      const taskTitle = request.params.arguments?.title as string;
      const taskNotes = request.params.arguments?.notes as string;
      const taskStatus = request.params.arguments?.status as string;
      const taskDue = request.params.arguments?.due as string;

      if (!taskTitle) {
        throw new Error("Task title is required");
      }

      const task: tasks_v1.Schema$Task = {
        title: taskTitle,
        status: taskStatus || "needsAction",
      };
      if (taskNotes) task.notes = taskNotes;
      if (taskDue) task.due = normalizeDueDate(taskDue);
      const taskCompleted = request.params.arguments?.completed as string;
      if (taskCompleted) task.completed = toRfc3339(taskCompleted);

      const parent = request.params.arguments?.parent as string | undefined;
      const previous = request.params.arguments?.previous as string | undefined;

      console.error(`Creating task "${taskTitle}" in task list ${taskListId}`);
      const taskResponse = await tasks.tasks.insert({
        tasklist: taskListId,
        requestBody: task,
        ...(parent ? { parent } : {}),
        ...(previous ? { previous } : {}),
      });

      return {
        content: [
          {
            type: "text",
            text: `Task created: ${this.formatTask(taskResponse.data)}`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error creating task:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error creating task: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async update(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      // First, get available task lists to ensure we have a valid list
      const taskListsResponse = await tasks.tasklists.list({
        maxResults: MAX_TASK_RESULTS,
      });

      const taskLists = taskListsResponse.data.items || [];
      if (!taskLists.length) {
        throw new Error("No task lists found in your Google Tasks account");
      }

      // Use the first task list if none specified
      let taskListId = request.params.arguments?.taskListId as string;
      if (!taskListId || taskListId === "@default") {
        taskListId = taskLists[0].id!;
        console.error(
          `Using first task list: ${taskLists[0].title} (${taskListId})`
        );
      }

      const taskId = request.params.arguments?.id as string;
      const taskTitle = request.params.arguments?.title as string;
      const taskNotes = request.params.arguments?.notes as string;
      const taskStatus = request.params.arguments?.status as string;
      const taskDue = request.params.arguments?.due as string;

      if (!taskId) {
        throw new Error("Task ID is required");
      }

      // Use patch so omitted fields (e.g. title) are preserved.
      const task: tasks_v1.Schema$Task = { id: taskId };
      if (taskTitle !== undefined) task.title = taskTitle;
      if (taskNotes !== undefined) task.notes = taskNotes;
      if (taskStatus !== undefined) task.status = taskStatus;
      if (taskDue !== undefined)
        task.due = taskDue === "" ? null : normalizeDueDate(taskDue);
      const taskCompleted = request.params.arguments?.completed as string;
      if (taskCompleted !== undefined)
        task.completed = taskCompleted === "" ? null : toRfc3339(taskCompleted);
      const taskDeleted = request.params.arguments?.deleted as boolean;
      if (taskDeleted !== undefined) task.deleted = taskDeleted;

      const taskResponse = await tasks.tasks.patch({
        tasklist: taskListId,
        task: taskId,
        requestBody: task,
      });

      return {
        content: [
          {
            type: "text",
            text: `Task updated: ${this.formatTask(taskResponse.data)}`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error updating task:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error updating task: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async list(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const allTasks = await this._list(request, tasks);
      const taskList = this.formatTaskList(allTasks);

      return {
        content: [
          {
            type: "text",
            text: `Found ${allTasks.length} tasks:\n${taskList}`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error listing tasks:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error listing tasks: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async delete(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      // First, get available task lists to ensure we have a valid list
      const taskListsResponse = await tasks.tasklists.list({
        maxResults: MAX_TASK_RESULTS,
      });

      const taskLists = taskListsResponse.data.items || [];
      if (!taskLists.length) {
        throw new Error("No task lists found in your Google Tasks account");
      }

      // Use the first task list if none specified
      let taskListId = request.params.arguments?.taskListId as string;
      if (!taskListId || taskListId === "@default") {
        taskListId = taskLists[0].id!;
        console.error(
          `Using first task list: ${taskLists[0].title} (${taskListId})`
        );
      }

      const taskId = request.params.arguments?.id as string;

      if (!taskId) {
        throw new Error("Task ID is required");
      }

      await tasks.tasks.delete({
        tasklist: taskListId,
        task: taskId,
      });

      return {
        content: [
          {
            type: "text",
            text: `Task ${taskId} deleted`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error deleting task:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error deleting task: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async search(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const userQuery = request.params.arguments?.query as string;

      const allTasks = await this._list(request, tasks);
      const filteredItems = allTasks.filter(
        (task) =>
          task.title?.toLowerCase().includes(userQuery.toLowerCase()) ||
          task.notes?.toLowerCase().includes(userQuery.toLowerCase())
      );

      const taskList = this.formatTaskList(filteredItems);

      return {
        content: [
          {
            type: "text",
            text: `Found ${filteredItems.length} tasks matching "${userQuery}":\n${taskList}`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error searching tasks:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error searching tasks: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async clear(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      // First, get available task lists to ensure we have a valid list
      const taskListsResponse = await tasks.tasklists.list({
        maxResults: MAX_TASK_RESULTS,
      });

      const taskLists = taskListsResponse.data.items || [];
      if (!taskLists.length) {
        throw new Error("No task lists found in your Google Tasks account");
      }

      // Use the first task list if none specified
      let taskListId = request.params.arguments?.taskListId as string;
      if (!taskListId || taskListId === "@default") {
        taskListId = taskLists[0].id!;
        console.error(
          `Using first task list: ${taskLists[0].title} (${taskListId})`
        );
      }

      await tasks.tasks.clear({
        tasklist: taskListId,
      });

      return {
        content: [
          {
            type: "text",
            text: `Cleared all completed tasks from list`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error clearing tasks:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error clearing tasks: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async listTaskLists(
    _request: CallToolRequest,
    tasks: tasks_v1.Tasks
  ) {
    try {
      const taskListsResponse = await tasks.tasklists.list({
        maxResults: MAX_TASK_RESULTS,
      });

      const taskLists = taskListsResponse.data.items || [];

      const lines = taskLists.map(
        (list) =>
          `- ${list.title} | id:${list.id} | updated:${list.updated ?? "unknown"}`
      );

      return {
        content: [
          {
            type: "text",
            text: `Found ${taskLists.length} task list(s):\n${lines.join("\n")}`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error listing task lists:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error listing task lists: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async listWithTree(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const taskListId = request.params.arguments?.taskListId as string;
      if (!taskListId) {
        throw new Error("taskListId is required");
      }

      const showCompleted =
        (request.params.arguments?.showCompleted as boolean) ?? false;
      const showHidden =
        (request.params.arguments?.showHidden as boolean) ?? false;

      const allTasks = await this._fetchAllTasksFromList(
        tasks,
        taskListId,
        showCompleted,
        showHidden
      );

      // Group tasks by parent ID (undefined/null = root)
      const childrenMap = new Map<string, tasks_v1.Schema$Task[]>();
      const rootTasks: tasks_v1.Schema$Task[] = [];

      for (const task of allTasks) {
        const parentId = task.parent ?? null;
        if (parentId) {
          const siblings = childrenMap.get(parentId) || [];
          siblings.push(task);
          childrenMap.set(parentId, siblings);
        } else {
          rootTasks.push(task);
        }
      }

      // Sort each group by position (lexicographic string comparison)
      const sortByPosition = (a: tasks_v1.Schema$Task, b: tasks_v1.Schema$Task) =>
        (a.position ?? "").localeCompare(b.position ?? "");

      rootTasks.sort(sortByPosition);
      for (const [, children] of childrenMap) {
        children.sort(sortByPosition);
      }

      // DFS to flatten tree into indented lines
      const lines: string[] = [];

      const dfs = (taskList: tasks_v1.Schema$Task[], depth: number) => {
        for (const task of taskList) {
          const indent = "  ".repeat(depth);
          const status = task.status === "completed" ? "[x]" : "[ ]";
          const title = task.title || "(no title)";
          const duePart = task.due ? ` (due: ${task.due})` : "";
          const parentPart = task.parent ? ` parent:${task.parent}` : "";
          lines.push(
            `${indent}${status} ${title}${duePart} | id:${task.id}${parentPart}`
          );

          // Recurse into children
          const children = childrenMap.get(task.id!) || [];
          if (children.length > 0) {
            dfs(children, depth + 1);
          }
        }
      };

      dfs(rootTasks, 0);

      return {
        content: [
          {
            type: "text",
            text: `Task tree (${allTasks.length} tasks):\n${lines.join("\n")}`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error listing tasks as tree:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error listing tasks as tree: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  static async move(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const taskListId = request.params.arguments?.taskListId as string;
      const taskId = request.params.arguments?.taskId as string;

      if (!taskListId) {
        throw new Error("taskListId is required");
      }
      if (!taskId) {
        throw new Error("taskId is required");
      }

      const parent = request.params.arguments?.parent as string | undefined;
      const previous = request.params.arguments?.previous as string | undefined;
      const destinationTasklist = request.params.arguments
        ?.destinationTasklist as string | undefined;

      const moveParams: {
        tasklist: string;
        task: string;
        parent?: string;
        previous?: string;
        destinationTasklist?: string;
      } = {
        tasklist: taskListId,
        task: taskId,
      };

      if (parent) moveParams.parent = parent;
      if (previous) moveParams.previous = previous;
      if (destinationTasklist)
        moveParams.destinationTasklist = destinationTasklist;

      const response = await tasks.tasks.move(moveParams);
      const movedTask = response.data;

      return {
        content: [
          {
            type: "text",
            text: `Task moved: ${movedTask.title} | id:${movedTask.id} | position:${movedTask.position} | parent:${movedTask.parent ?? "none"}`,
          },
        ],
        isError: false,
      };
    } catch (error) {
      console.error("Error moving task:", error);
      return {
        content: [
          {
            type: "text",
            text: `Error moving task: ${
              error instanceof Error ? error.message : String(error)
            }`,
          },
        ],
        isError: true,
      };
    }
  }

  private static ok(text: string) {
    return { content: [{ type: "text", text }], isError: false };
  }

  private static fail(action: string, error: unknown) {
    console.error(`Error ${action}:`, error);
    return {
      content: [
        {
          type: "text",
          text: `Error ${action}: ${
            error instanceof Error ? error.message : String(error)
          }`,
        },
      ],
      isError: true,
    };
  }

  private static formatTaskListMeta(list: tasks_v1.Schema$TaskList) {
    return `${list.title} | id:${list.id} | updated:${list.updated ?? "unknown"}`;
  }

  static async get(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const args = request.params.arguments ?? {};
      const response = await tasks.tasks.get({
        tasklist: (args.taskListId as string) || "@default",
        task: args.id as string,
      });
      return this.ok(this.formatTask(response.data));
    } catch (error) {
      return this.fail("getting task", error);
    }
  }

  static async getTaskList(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const response = await tasks.tasklists.get({
        tasklist: request.params.arguments?.taskListId as string,
      });
      return this.ok(this.formatTaskListMeta(response.data));
    } catch (error) {
      return this.fail("getting task list", error);
    }
  }

  static async createTaskList(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const title = request.params.arguments?.title as string;
      if (!title) throw new Error("title is required");
      const response = await tasks.tasklists.insert({ requestBody: { title } });
      return this.ok(`Task list created: ${this.formatTaskListMeta(response.data)}`);
    } catch (error) {
      return this.fail("creating task list", error);
    }
  }

  static async updateTaskList(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const args = request.params.arguments ?? {};
      const title = args.title as string;
      if (!title) throw new Error("title is required");
      const response = await tasks.tasklists.patch({
        tasklist: args.taskListId as string,
        requestBody: { title },
      });
      return this.ok(`Task list updated: ${this.formatTaskListMeta(response.data)}`);
    } catch (error) {
      return this.fail("updating task list", error);
    }
  }

  static async deleteTaskList(request: CallToolRequest, tasks: tasks_v1.Tasks) {
    try {
      const taskListId = request.params.arguments?.taskListId as string;
      if (!taskListId) throw new Error("taskListId is required");
      await tasks.tasklists.delete({ tasklist: taskListId });
      return this.ok(`Task list ${taskListId} deleted`);
    } catch (error) {
      return this.fail("deleting task list", error);
    }
  }
}
