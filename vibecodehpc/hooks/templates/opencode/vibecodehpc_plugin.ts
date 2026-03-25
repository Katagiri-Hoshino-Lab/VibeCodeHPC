// VibeCodeHPC OpenCode plugin — auto-generated, do not edit.
//
// Hooks:
//   event (session.created) → update agent registry with session ID
//
// Plugin API: https://opencode.ai/docs/plugins

import { readFileSync, writeFileSync, appendFileSync, existsSync } from "fs";
import { join } from "path";

// --- Placeholder tokens replaced by OpenCodeAdapter.setup_hooks() ---
const PROJECT_ROOT = "__PROJECT_ROOT__";
const AGENT_ID = "__AGENT_ID__";

// --- Paths ---
const REGISTRY_PATH = join(PROJECT_ROOT, "agent_registry.jsonl");
const AGENT_TABLE_PATH = join(
  PROJECT_ROOT,
  "Agent-shared",
  "agent_and_pane_id_table.jsonl"
);

// --- Helpers ---

function readAgentId(directory: string): string {
  const agentIdPath = join(directory, ".opencode", "agent_id.txt");
  try {
    return readFileSync(agentIdPath, "utf-8").trim();
  } catch {
    return AGENT_ID;
  }
}

function updateAgentTable(sessionId: string): void {
  if (!existsSync(AGENT_TABLE_PATH)) return;
  try {
    const lines = readFileSync(AGENT_TABLE_PATH, "utf-8")
      .trim()
      .split("\n")
      .filter(Boolean);
    const updated = lines.map((line) => {
      try {
        const entry = JSON.parse(line);
        if (entry.agent_id === AGENT_ID) {
          entry.session_id = sessionId;
          entry.status = "running";
          entry.last_updated = new Date().toISOString();
          return JSON.stringify(entry);
        }
        return line;
      } catch {
        return line;
      }
    });
    writeFileSync(AGENT_TABLE_PATH, updated.join("\n") + "\n", "utf-8");
  } catch {
    // best-effort
  }
}

function appendRegistryEntry(sessionId: string): void {
  const entry = JSON.stringify({
    agent_id: AGENT_ID,
    session_id: sessionId,
    timestamp: new Date().toISOString(),
    source: "opencode_plugin",
  });
  try {
    appendFileSync(REGISTRY_PATH, entry + "\n", "utf-8");
  } catch {
    // best-effort
  }
}

// --- Plugin export ---

export const VibeCodeHPC = async ({ directory }: { directory: string }) => {
  const agentId = readAgentId(directory);

  return {
    // ---- session.created → registry update ----
    event: async (input: { event: { type: string; properties?: any } }) => {
      if (input.event.type !== "session.created") return;
      const sessionId = input.event.properties?.info?.id ?? "";
      if (!sessionId) return;

      appendRegistryEntry(sessionId);
      updateAgentTable(sessionId);
    },
  };
};
