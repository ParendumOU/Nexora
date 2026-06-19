// Shared integration type definitions

export interface TelegramSyncHub {
  setup_complete?: boolean;
  group_chat_id?: number;
  telegram_user_id?: number;
  project_topics?: Record<string, number>;
}

export interface IntegrationItem {
  id: string;
  name: string;
  integration_type: string;
  config: Record<string, unknown> & { token?: string; sync_hub?: TelegramSyncHub };
  is_active: boolean;
  is_default: boolean;
  pending_count?: number;
  created_at: string;
}

export interface IntegrationTypeDef {
  value: string;
  label: string;
  dot: string;
  color: string;
  comingSoon?: boolean;
  hint?: string;
}

export const INTEGRATION_TYPES: IntegrationTypeDef[] = [
  {
    value: "telegram", label: "Telegram", dot: "bg-blue-400", color: "text-blue-400",
    hint: "Create a bot via @BotFather on Telegram. Copy the token it gives you.",
  },
  {
    value: "slack", label: "Slack", dot: "bg-yellow-400", color: "text-yellow-400",
    comingSoon: true, hint: "Slack bot integration — coming soon.",
  },
  {
    value: "discord", label: "Discord", dot: "bg-indigo-400", color: "text-indigo-400",
    comingSoon: true, hint: "Discord bot integration — coming soon.",
  },
  {
    value: "whatsapp", label: "WhatsApp", dot: "bg-green-400", color: "text-green-400",
    comingSoon: true, hint: "WhatsApp Business API — coming soon.",
  },
];

export function integrationDef(type: string): IntegrationTypeDef {
  return INTEGRATION_TYPES.find((t) => t.value === type) ?? {
    value: type, label: type, dot: "bg-muted", color: "text-muted-foreground",
  };
}
