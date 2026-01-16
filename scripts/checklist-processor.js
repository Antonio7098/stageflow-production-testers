#!/usr/bin/env node
/**
 * Parallel Checklist Processor for OpenCode
 * 
 * Iterates through ROADMAP_CHECKLIST.md, spawning 5 parallel OpenCode subagents
 * to work on items in batches until all are complete.
 */

const { spawn } = require("child_process");
const { readFileSync, writeFileSync, existsSync, mkdirSync, openSync, closeSync } = require("fs");
const { join } = require("path");

const VERSION = "1.0.0";

// Configuration
const CHECKLIST_FILE = "docs/roadmap/ROADMAP_CHECKLIST.md";
const AGENT_PROMPT_FILE = "docs/prompts/AGENT_SYSTEM_PROMPT.md";
const BATCH_SIZE = 5;
const MAX_ITERATIONS_PER_ITEM = 20;
const COMPLETION_PROMISE = "ITEM_COMPLETE";

// Type definitions (using JSDoc for better Node.js compatibility)

/**
 * @typedef {Object} ChecklistItem
 * @property {string} id
 * @property {string} target
 * @property {string} priority
 * @property {string} risk
 * @property {string} status
 * @property {string} tier
 * @property {string} section
 */

/**
 * @typedef {Object} BatchResult
 * @property {ChecklistItem} item
 * @property {boolean} success
 * @property {string} [error]
 * @property {string} [output]
 */

// Lazy-load agent system prompt (if present)
let agentSystemPrompt = "";
if (existsSync(AGENT_PROMPT_FILE)) {
  agentSystemPrompt = readFileSync(AGENT_PROMPT_FILE, "utf-8");
} else {
  console.warn(`⚠️  Missing ${AGENT_PROMPT_FILE}. Agents will only receive checklist instructions.`);
}

// State management paths (needed before we parse CLI flags that inspect state)
const stateDir = join(process.cwd(), ".checklist-processor");
const statePath = join(stateDir, "state.json");
const checkpointPath = join(stateDir, "checkpoint.json");

// Parse command line arguments
const args = process.argv.slice(2);

if (args.includes("--help") || args.includes("-h")) {
  console.log(`
Parallel Checklist Processor - OpenCode Task Tool Orchestration

Usage:
  node checklist-processor.js [options]

Options:
  --batch-size N        Number of parallel items to process (default: 5)
  --max-iterations N   Max iterations per item (default: 20)
  --dry-run            Show what would be processed without running
  --resume             Resume from last checkpoint
  --status             Show current processing status
  --version, -v        Show version
  --help, -h           Show this help

Examples:
  node checklist-processor.js                    # Process all items in batches of 5
  node checklist-processor.js --batch-size 3     # Process 3 items at a time
  node checklist-processor.js --dry-run          # Preview without execution
  node checklist-processor.js --status           # Check current status
`);
  process.exit(0);
}

if (args.includes("--version") || args.includes("-v")) {
  console.log(`checklist-processor v${VERSION}`);
  process.exit(0);
}

let batchSize = BATCH_SIZE;
let maxIterations = MAX_ITERATIONS_PER_ITEM;
let dryRun = false;
let resume = false;

// Parse options
for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg === "--batch-size") {
    const val = args[++i];
    if (!val || isNaN(parseInt(val))) {
      console.error("Error: --batch-size requires a number");
      process.exit(1);
    }
    batchSize = parseInt(val);
  } else if (arg === "--max-iterations") {
    const val = args[++i];
    if (!val || isNaN(parseInt(val))) {
      console.error("Error: --max-iterations requires a number");
      process.exit(1);
    }
    maxIterations = parseInt(val);
  } else if (arg === "--dry-run") {
    dryRun = true;
  } else if (arg === "--resume") {
    resume = true;
  } else if (arg === "--status") {
    showStatus();
    process.exit(0);
  } else if (arg.startsWith("-")) {
    console.error(`Error: Unknown option: ${arg}`);
    process.exit(1);
  }
}

/**
 * @typedef {Object} ProcessorState
 * @property {boolean} active
 * @property {number} currentBatch
 * @property {number} totalBatches
 * @property {string[]} itemsProcessed
 * @property {string[]} itemsCompleted
 * @property {string[]} itemsFailed
 * @property {string} startedAt
 * @property {string} lastCheckpoint
 * @property {string} [completedAt]
 */

function ensureStateDir() {
  if (!existsSync(stateDir)) {
    mkdirSync(stateDir, { recursive: true });
  }
}

function saveState(state) {
  ensureStateDir();
  writeFileSync(statePath, JSON.stringify(state, null, 2));
}

function loadState() {
  if (!existsSync(statePath)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(statePath, "utf-8"));
  } catch {
    return null;
  }
}

function saveCheckpoint(items) {
  ensureStateDir();
  const checkpoint = {
    timestamp: new Date().toISOString(),
    items: items.map(item => ({
      id: item.id,
      status: item.status
    }))
  };
  writeFileSync(checkpointPath, JSON.stringify(checkpoint, null, 2));
}

// Parse checklist from markdown
function parseChecklist() {
  if (!existsSync(CHECKLIST_FILE)) {
    console.error(`Error: Checklist file not found: ${CHECKLIST_FILE}`);
    process.exit(1);
  }

  const content = readFileSync(CHECKLIST_FILE, "utf-8");
  const lines = content.split("\n");
  const items = [];
  
  let currentTier = "";
  let currentSection = "";
  let inTable = false;

  for (const line of lines) {
    // Track tier and section
    if (line.startsWith("## Tier ")) {
      currentTier = line.replace("## ", "");
      currentSection = "";
      continue;
    }
    
    if (line.startsWith("### ")) {
      currentSection = line.replace("### ", "");
      continue;
    }

    // Track table headers
    if (line.includes("| ID |") && line.includes("| Target |")) {
      inTable = true;
      continue;
    }

    const trimmed = line.trim();

    // Parse table rows (markdown rows start with '|')
    if (inTable && trimmed.startsWith("|")) {
      const cols = trimmed
        .split("|")
        .map(c => c.trim())
        .filter(Boolean);
      if (cols.length >= 5) {
        const id = cols[0];
        const target = cols[1];
        const priority = cols[2];
        const risk = cols[3];
        const status = cols[4];

        // Skip header rows and separators
        if (id === "ID" || id === "----") continue;

        items.push({
          id,
          target,
          priority,
          risk,
          status,
          tier: currentTier,
          section: currentSection
        });
      }
    }

    // Exit table when we hit a non-table line
    if (inTable && trimmed && !trimmed.includes("|")) {
      inTable = false;
    }
  }

  return items;
}

// Show current status
function showStatus() {
  const state = loadState();
  const items = parseChecklist();
  
  console.log(`
╔══════════════════════════════════════════════════════════════════╗
║                Checklist Processor Status                         ║
╚══════════════════════════════════════════════════════════════════╝
`);

  if (!state) {
    console.log("⏹️  No active processing session");
    console.log(`📋 Total items in checklist: ${items.length}`);
    return;
  }

  const completed = items.filter(item => item.status.includes("✅") || state.itemsCompleted.includes(item.id));
  const failed = items.filter(item => state.itemsFailed.includes(item.id));
  const remaining = items.length - completed.length - failed.length;

  console.log(`🔄 Active session: ${state.active ? "Yes" : "No"}`);
  console.log(`📊 Progress: ${completed.length} completed, ${failed.length} failed, ${remaining.length} remaining`);
  console.log(`📦 Current batch: ${state.currentBatch} / ${state.totalBatches}`);
  console.log(`⏱️  Started: ${state.startedAt}`);
  console.log(`🕐 Last checkpoint: ${state.lastCheckpoint}`);
  
  if (state.itemsFailed.length > 0) {
    console.log(`\n❌ Failed items: ${state.itemsFailed.join(", ")}`);
  }
}

// Produce the full OpenCode prompt (system + checklist context)
function generateItemPrompt(item) {
  const filledSystemPrompt = injectSystemPromptValues(agentSystemPrompt, item);

  const checklistContext = `
# Checklist Item: ${item.id}

## Task
Complete the following checklist item from the Stageflow Stress-Testing Roadmap:

**ID**: ${item.id}
**Target**: ${item.target}
**Priority**: ${item.priority}
**Risk**: ${item.risk}
**Tier**: ${item.tier || "N/A"}
**Section**: ${item.section || "N/A"}

## Instructions
1. Follow the Stageflow agent mission prompt above.
2. Focus on the specific target described here.
3. Create and validate all required artifacts, tests, and documentation.
4. Update the roadmap checklist entry when genuinely complete.
5. **CRITICAL**: When you are truly finished, you MUST output exactly <promise>${COMPLETION_PROMISE}</promise> on its own line. Without this, the task will be marked as failed.

## Current Status
${item.status}

Treat this as a self-directed mission: finish the task end-to-end, including research, implementation, testing, and reporting.
`.trim();

  return filledSystemPrompt
    ? `${filledSystemPrompt}\n\n---\n\n${checklistContext}`
    : checklistContext;
}

function injectSystemPromptValues(systemPrompt, item) {
  if (!systemPrompt) return "";

  const replacements = {
    "{{ENTRY_ID}}": item.id,
    "{{ENTRY_TITLE}}": item.target,
    "{{PRIORITY}}": item.priority,
    "{{RISK_CLASS}}": item.risk,
    "{{INDUSTRY}}": item.section || "N/A",
    "{{DEPLOYMENT_MODE}}": "N/A"
  };

  let filled = systemPrompt;
  for (const [token, value] of Object.entries(replacements)) {
    const pattern = new RegExp(token, "g");
    filled = filled.replace(pattern, value);
  }

  return filled;
}

// Run a single checklist item via OpenCode CLI
function runChecklistItem(item, prompt) {
  return new Promise(resolve => {
    console.log(`\n🔄 Starting item ${item.id}: ${item.target.substring(0, 60)}...`);

    if (dryRun) {
      console.log(`[DRY RUN] Would process: ${item.id}`);
      resolve({ item, success: true, output: "" });
      return;
    }

    const promptArg = prompt;
    console.log(`[DEBUG] Prompt length: ${promptArg.length}, Starts with: ${promptArg.substring(0, 20).replace(/\n/g, "\\n")}`);
    
    const args = [
      "run",
      "--model",
      "opencode/minimax-m2.1-free"
    ];

    const child = spawn("opencode", args, { env: process.env });
    
    // Write prompt to stdin to avoid argument length limits
    child.stdin.write(prompt);
    child.stdin.end();

    let output = "";
    const logPath = join(stateDir, `${item.id}.log`);
    const logFd = openSync(logPath, "w");
    writeFileSync(logPath, `=== ${item.id}: ${item.target} ===\n\n`);

    child.stdout.on("data", chunk => {
      const text = chunk.toString();
      output += text;
      process.stdout.write(`[${item.id}] ${text}`);
      writeFileSync(logPath, text, { flag: "a" });
    });

    child.stderr.on("data", chunk => {
      const text = chunk.toString();
      output += text;
      process.stderr.write(`[${item.id}] ${text}`);
      writeFileSync(logPath, text, { flag: "a" });
    });

    child.on("error", error => {
      console.log(`❌ Error launching OpenCode for ${item.id}: ${error.message}`);
      writeFileSync(logPath, `ERROR: ${error.message}\n`, { flag: "a" });
      resolve({ item, success: false, error: error.message, output });
    });

    child.on("close", code => {
      closeSync(logFd);
      const completed = output.includes(`<promise>${COMPLETION_PROMISE}</promise>`);
      if (code === 0 && completed) {
        console.log(`✅ Completed item ${item.id}`);
        resolve({ item, success: true, output });
      } else {
        const reason = completed ? `Process exited with code ${code}` : "Completion promise not detected";
        console.log(`❌ Failed item ${item.id}: ${reason}`);
        resolve({ item, success: false, error: reason, output });
      }
    });
  });
}

// Process a batch of items in parallel
async function processBatch(batch, batchNumber) {
  console.log(`\n🚀 Processing Batch ${batchNumber} (${batch.length} items)`);
  console.log("═".repeat(60));

  const prompts = batch.map(item => generateItemPrompt(item));
  const tasks = [];

  // Spawn parallel OpenCode tasks
  for (let i = 0; i < batch.length; i++) {
    const item = batch[i];
    const prompt = prompts[i];
    
    const task = () => runChecklistItem(item, prompt);
    tasks.push(task());
  }

  // Wait for all tasks in this batch to complete
  const results = await Promise.all(tasks);
  
  // Update state with results
  const state = loadState();
  if (!state) {
    throw new Error("Processor state missing while saving batch results");
  }
  for (const result of results) {
    if (result.success) {
      state.itemsCompleted.push(result.item.id);
    } else {
      state.itemsFailed.push(result.item.id);
    }
    state.itemsProcessed.push(result.item.id);
  }
  
  state.currentBatch = batchNumber + 1;
  state.lastCheckpoint = new Date().toISOString();
  saveState(state);
  
  // Update checklist file with completed items
  if (!dryRun) {
    updateChecklistStatus(results);
    saveCheckpoint(parseChecklist());
  }
  
  console.log(`\n📊 Batch ${batchNumber} complete:`);
  console.log(`   ✅ Completed: ${results.filter(r => r.success).length}`);
  console.log(`   ❌ Failed: ${results.filter(r => !r.success).length}`);
  return results;
}

// Update checklist status in markdown file
function updateChecklistStatus(results) {
  let content = readFileSync(CHECKLIST_FILE, "utf-8");
  
  for (const result of results) {
    if (result.success) {
      // Replace status for completed items
      const oldStatus = result.item.status;
      const newStatus = oldStatus.replace("☐ Not Started", "✅ Completed");
      
      // Update the table row
      const oldRow = `| ${result.item.id} | ${result.item.target} | ${result.item.priority} | ${result.item.risk} | ${oldStatus} |`;
      const newRow = `| ${result.item.id} | ${result.item.target} | ${result.item.priority} | ${result.item.risk} | ${newStatus} |`;
      
      content = content.replace(oldRow, newRow);
    }
  }
  
  writeFileSync(CHECKLIST_FILE, content);
}

// Main processing function
async function processChecklist() {
  const items = parseChecklist();
  
  // Filter out already completed items
  const incompleteItems = items.filter(item => 
    !item.status.includes("✅") && item.status.includes("☐ Not Started")
  );
  
  console.log(`
╔══════════════════════════════════════════════════════════════════╗
║              Parallel Checklist Processor                        ║
║              OpenCode Task Tool Orchestration                     ║
╚══════════════════════════════════════════════════════════════════╝
`);

  console.log(`📋 Total items: ${items.length}`);
  console.log(`🔄 Incomplete items: ${incompleteItems.length}`);
  console.log(`📦 Batch size: ${batchSize}`);
  console.log(`🔢 Max iterations per item: ${maxIterations}`);
  
  if (dryRun) {
    console.log(`🔍 DRY RUN MODE - No actual execution`);
  }

  // Create batches
  const batches = [];
  for (let i = 0; i < incompleteItems.length; i += batchSize) {
    batches.push(incompleteItems.slice(i, i + batchSize));
  }

  console.log(`📊 Total batches: ${batches.length}`);

  // Initialize or resume state
  let state = loadState();
  if (resume && state) {
    console.log(`🔄 Resuming from batch ${state.currentBatch}`);
  } else {
    state = {
      active: true,
      currentBatch: 0,
      totalBatches: batches.length,
      itemsProcessed: [],
      itemsCompleted: [],
      itemsFailed: [],
      startedAt: new Date().toISOString(),
      lastCheckpoint: new Date().toISOString()
    };
    saveState(state);
  }

  // Process each batch
  for (let i = state.currentBatch; i < batches.length; i++) {
    await processBatch(batches[i], i + 1);
    
    // Small delay between batches
    if (!dryRun && i < batches.length - 1) {
      console.log("\n⏳ Waiting 5 seconds before next batch...");
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
  }

  // Final summary
  state.active = false;
  state.completedAt = new Date().toISOString();
  saveState(state);

  console.log(`
╔══════════════════════════════════════════════════════════════════╗
║                      Processing Complete                          ║
╚══════════════════════════════════════════════════════════════════╝
`);
  console.log(`✅ Completed: ${state.itemsCompleted.length}`);
  console.log(`❌ Failed: ${state.itemsFailed.length}`);
  console.log(`⏱️  Total time: ${Math.floor((Date.now() - new Date(state.startedAt).getTime()) / 1000 / 60)} minutes`);
  
  if (state.itemsFailed.length > 0) {
    console.log(`\n❌ Failed items: ${state.itemsFailed.join(", ")}`);
    console.log(`💡 Run with --resume to retry failed items`);
  }
}

// Handle interruption
process.on("SIGINT", () => {
  console.log("\n🛑 Interrupted. State saved. Use --resume to continue.");
  process.exit(0);
});

// Run the processor
processChecklist().catch(error => {
  console.error("Fatal error:", error);
  process.exit(1);
});