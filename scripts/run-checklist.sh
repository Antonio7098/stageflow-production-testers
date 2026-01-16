#!/bin/bash
# Parallel Checklist Processor Runner

echo "🚀 Starting Parallel Checklist Processor..."
echo "This will process ROADMAP_CHECKLIST.md using 5 parallel OpenCode subagents"
echo ""

# Check if checklist file exists
if [ ! -f "ROADMAP_CHECKLIST.md" ]; then
    echo "❌ Error: ROADMAP_CHECKLIST.md not found"
    exit 1
fi

# Check if OpenCode is available
if ! command -v opencode &> /dev/null; then
    echo "❌ Error: OpenCode not found in PATH"
    exit 1
fi

# Run the processor
node checklist-processor.js "$@"