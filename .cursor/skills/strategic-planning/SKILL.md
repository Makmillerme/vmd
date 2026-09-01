---
name: strategic-planning
description: Activates sequential-thinking MCP for complex refactoring and feature implementation planning. Generates risk assessment, step-by-step plan, and dependency map. Use before complex refactoring, major feature implementation, or when the user requests strategic planning or risk analysis.
---

# Strategic Planning

This skill activates sequential-thinking MCP to perform comprehensive planning for complex tasks, generating risk assessments, step-by-step plans, and dependency maps.

**Align with workspace:** for substantial work, use Composer **Plan** mode **together** with **`/plan`** (sequential-thinking); after agreement, **close Plan** and implement in **Agent** with **`/serena`**. See [`senior-agent-workflow.mdc`](../../rules/senior-agent-workflow.mdc).

## When to Activate

Activate this skill automatically when:
- User requests complex refactoring
- User requests new feature implementation
- Task involves multiple components or dependencies
- User explicitly requests strategic planning or risk assessment
- Task scope is unclear or potentially risky

## Workflow

### Step 1: Activate Sequential-Thinking MCP

Use `sequentialthinking` tool from `user-sequential-thinking` MCP server:

```typescript
call_mcp_tool({
  server: "user-sequential-thinking",
  toolName: "sequentialthinking",
  arguments: {
    thought: "[Initial analysis of the task]",
    thoughtNumber: 1,
    totalThoughts: [initial estimate],
    nextThoughtNeeded: true
  }
})
```

### Step 2: Analysis Process

Structure the thinking process to cover:

1. **Task Understanding**
   - Analyze requirements and scope
   - Identify affected components
   - Understand current architecture

2. **Risk Assessment**
   - Identify potential breaking changes
   - Assess impact on existing functionality
   - Evaluate data migration risks
   - Consider performance implications
   - Review security concerns

3. **Dependency Mapping**
   - Map component dependencies
   - Identify external dependencies
   - List affected files and modules
   - Document integration points

4. **Step-by-Step Plan**
   - Break down into manageable steps
   - Define execution order
   - Identify prerequisites for each step
   - Set validation checkpoints

### Step 3: Output Format

Present results in structured format:

```markdown
# Strategic Plan: [Task Name]

## Risk Assessment

### High Risk
- [Risk 1]: [Description] - [Mitigation strategy]
- [Risk 2]: [Description] - [Mitigation strategy]

### Medium Risk
- [Risk 1]: [Description] - [Mitigation strategy]

### Low Risk
- [Risk 1]: [Description]

## Dependency Map

```
[Component/Module]
├── Depends on: [Dependency 1, Dependency 2]
├── Affects: [Component 1, Component 2]
└── Integration points: [API, Database, etc.]
```

## Step-by-Step Plan

1. **[Step Name]**
   - Prerequisites: [List]
   - Actions: [Detailed actions]
   - Validation: [How to verify]

2. **[Step Name]**
   - Prerequisites: [List]
   - Actions: [Detailed actions]
   - Validation: [How to verify]

[... continue for all steps]
```

## Best Practices

1. **Adjust Total Thoughts**: Start with an estimate, but adjust `totalThoughts` as analysis progresses
2. **Revise When Needed**: Use `isRevision: true` to refine earlier thoughts
3. **Branch for Alternatives**: Use branching when exploring multiple approaches
4. **Complete Analysis**: Only set `nextThoughtNeeded: false` when all aspects are covered
5. **Verify Hypothesis**: Generate solution hypothesis and verify it through the thinking process

## Integration with Other Skills

- **Before Backend Changes**: Use with `backend-and-data` skill for database impact assessment
- **Before Frontend Changes**: Use with `ui-engineering` skill for component dependency analysis
- **After Planning**: Update Serena MCP with planning results via `fullstack-development-workflow` skill
