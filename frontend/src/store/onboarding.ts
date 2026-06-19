import { create } from "zustand";
import { persist } from "zustand/middleware";

export const ONBOARDING_STEPS = [
  {
    title: "Your profile",
    description: "Add an avatar and display name — visible to your team and used by AI agents to know who they're working with.",
    route: "/profile",
  },
  {
    title: "Choose your interface",
    description: "Simple keeps things focused. Advanced unlocks the full management suite.",
    route: "/profile",
  },
  {
    title: "Contact info",
    description: "Add your contact details so AI agents can reference them when they need to know something about you.",
    route: "/profile",
  },
  {
    title: "AI Accounts",
    description: "Connect your AI providers — these power every conversation and agent.",
    route: "/settings",
  },
  {
    title: "Model Profiles",
    description: "Define routing rules to pick the right model for each task.",
    route: "/settings",
  },
  {
    title: "Fallback Chains",
    description: "Stack providers so Nexora auto-switches when one hits a rate limit.",
    route: "/settings",
  },
  {
    title: "Integrations",
    description: "Connect messaging platforms (Telegram, Slack, Discord) as channels, and link GitHub or GitLab accounts to import repositories.",
    route: "/settings",
  },
  {
    title: "Start chatting",
    description: "You're all set. Let's start your first conversation.",
    route: "/chat",
  },
] as const;

// Backwards through the manage nav: org → knowledge-bases → mcps → tools → skills → personas → agents → schedules → channels → projects → issues → proposals → tasks
export const ADVANCED_TOUR_STEPS = [
  {
    title: "Organization",
    description: "Your shared workspace. Manage members, assign roles (member, admin, owner), and generate invite links to bring teammates in.",
    route: "/org",
  },
  {
    title: "Knowledge Bases",
    description: "Upload documents, PDFs, and web pages. Nexora chunks and indexes them as vector embeddings so agents can search and cite them in context.",
    route: "/knowledge-bases",
  },
  {
    title: "MCP Servers",
    description: "Connect Model Context Protocol servers to expose external tools and resources to your agents automatically.",
    route: "/mcps",
  },
  {
    title: "Tools",
    description: "Individual capabilities agents can invoke.",
    route: "/tools",
  },
  {
    title: "Skills",
    description: "Reusable knowledge modules. Attaching a skill injects its instructions directly into the agent's context, shaping what it knows.",
    route: "/skills",
  },
  {
    title: "Personas",
    description: "Personality presets that define an agent's character, tone, and style. Attach one to give an agent a consistent identity.",
    route: "/personas",
  },
  {
    title: "Agents",
    description: "Your AI workforce. Each agent has a system prompt, persona, skills, tools, and a model profile — ready to run tasks autonomously.",
    route: "/agents",
  },
  {
    title: "Schedules",
    description: "Run an agent on autopilot. Set a cron expression or interval and a prompt — the agent fires automatically and can trigger full task chains.",
    route: "/schedules",
  },
  {
    title: "Channels",
    description: "Inbound event handlers. Channels listen for webhooks, cron triggers, Telegram/Slack messages, and dispatch them to an agent.",
    route: "/channels",
  },
  {
    title: "Projects",
    description: "Link a codebase to a PM agent and a Kanban board. Projects tie chats, tasks, and issues together with full Git context.",
    route: "/projects",
  },
  {
    title: "Proposals",
    description: "Agents can propose actions that need your sign-off before executing. Review, approve, or reject them here.",
    route: "/proposals",
  },
  {
    title: "Issues",
    description: "Track bugs and feature requests. Issues are visible to agents so they can be picked up and worked on autonomously.",
    route: "/issues",
  },
  {
    title: "Tasks",
    description: "The unit of work in Nexora. Tasks live in the Kanban board, can be assigned to agents or people, and flow through your pipeline to completion.",
    route: "/tasks",
  },
] as const;

interface OnboardingState {
  // Registration tour
  isActive: boolean;
  currentStep: number;
  start: () => void;
  goTo: (step: number) => void;
  finish: () => void;

  // Advanced mode tour
  advancedIsActive: boolean;
  advancedStep: number;
  hasSeenAdvancedTour: boolean;
  startAdvancedTour: () => void;
  goToAdvanced: (step: number) => void;
  finishAdvancedTour: () => void;
}

export const useOnboardingStore = create<OnboardingState>()(
  persist(
    (set) => ({
      isActive: false,
      currentStep: 0,
      start: () => set({ isActive: true, currentStep: 0 }),
      goTo: (step) => set({ currentStep: step }),
      finish: () => set({ isActive: false, currentStep: 0 }),

      advancedIsActive: false,
      advancedStep: 0,
      hasSeenAdvancedTour: false,
      startAdvancedTour: () => set({ advancedIsActive: true, advancedStep: 0, hasSeenAdvancedTour: true }),
      goToAdvanced: (step) => set({ advancedStep: step }),
      finishAdvancedTour: () => set({ advancedIsActive: false, advancedStep: 0 }),
    }),
    { name: "nx_onboarding" }
  )
);
