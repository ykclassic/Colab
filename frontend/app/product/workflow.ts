export type WorkflowKind = 'research' | 'quant' | 'agent' | 'governance' | 'artifact';

export type WorkflowPlan = {
  kind: WorkflowKind;
  name: string;
  description: string;
  stages: string[];
  destination: string;
};

const PLANS: Record<WorkflowKind, WorkflowPlan> = {
  research: {
    kind: 'research',
    name: 'Research → Quant → Governance',
    description: 'Build an evidence-backed research package, validate quantitative claims, then route the resulting artifact through governance.',
    stages: ['Research', 'Quant', 'Agents', 'Governance', 'Artifact / Report'],
    destination: '/research',
  },
  quant: {
    kind: 'quant',
    name: 'Quant Validation → Governance',
    description: 'Run quantitative analysis and validation, then prepare the resulting work for independent governance and artifact review.',
    stages: ['Quant', 'Agents', 'Governance', 'Artifact / Report'],
    destination: '/quant/overview',
  },
  agent: {
    kind: 'agent',
    name: 'Agent Workflow',
    description: 'Start with the agent team and coordinate the appropriate research, quant, engineering and governance stages.',
    stages: ['Agents', 'Research', 'Quant', 'Governance', 'Artifact / Report'],
    destination: '/agents',
  },
  governance: {
    kind: 'governance',
    name: 'Governance → Artifact / Report',
    description: 'Review an existing result against governance controls and prepare an auditable artifact or report.',
    stages: ['Governance', 'Artifact / Report'],
    destination: '/governance',
  },
  artifact: {
    kind: 'artifact',
    name: 'Artifact / Report',
    description: 'Inspect and organize an existing research, quant or governance result as a durable product artifact.',
    stages: ['Artifact / Report'],
    destination: '/artifacts',
  },
};

export function planWorkflow(goal: string): WorkflowPlan {
  const q = goal.trim().toLowerCase();
  if (/(report|artifact|deliverable|document)/.test(q)) return PLANS.artifact;
  if (/(govern|approve|compliance|release|review)/.test(q)) return PLANS.governance;
  if (/(quant|backtest|portfolio|strategy|alpha|factor|simulation|validation)/.test(q)) return PLANS.quant;
  if (/(agent|automate|workflow|coordinate|build)/.test(q)) return PLANS.agent;
  return PLANS.research;
}
