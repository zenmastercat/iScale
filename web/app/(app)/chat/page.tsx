"use client";
import { ChatView } from "@/components/chat/chat-view";
import { PageHeader } from "@/components/shared";
import { useT } from "@/lib/i18n";

export default function ChatPage() {
  const t = useT();
  return (
    <>
      <PageHeader title={t("Chat", "แชท")} />
      <ChatView />
    </>
  );
}
