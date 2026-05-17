"use client";

import { PanelLeftClose, PanelLeftOpen, Plus, Search, Settings } from "lucide-react";
import type { RefObject } from "react";

import { SidebarListItem } from "../hooks/use-session-history";
import type { FailureDiagnostic } from "../lib/types";


type AppSidebarProps = {
  collapsed: boolean;
  query: string;
  activeContextId: string;
  historyLoading: boolean;
  historyError: string;
  historyFailureDiagnostic: FailureDiagnostic | null;
  items: SidebarListItem[];
  searchInputRef: RefObject<HTMLInputElement | null>;
  onToggleCollapsed: () => void;
  onOpenSearch: () => void;
  onNewConversation: () => void;
  onReloadHistory: () => void;
  onOpenSettings: () => void;
  onChangeQuery: (value: string) => void;
  onSelectItem: (item: SidebarListItem) => void;
};

export function AppSidebar({
  collapsed,
  query,
  activeContextId,
  historyLoading,
  historyError,
  historyFailureDiagnostic,
  items,
  searchInputRef,
  onToggleCollapsed,
  onOpenSearch,
  onNewConversation,
  onReloadHistory,
  onOpenSettings,
  onChangeQuery,
  onSelectItem,
}: AppSidebarProps) {
  return (
    <aside className={`app-sidebar ${collapsed ? "is-collapsed" : ""}`}>
      <div className="sidebar-top">
        <div className="sidebar-title-row">
          {!collapsed ? <h1 className="sidebar-title">链接素材写作台</h1> : null}
          <div className="sidebar-actions">
            {collapsed ? (
              <button
                className="icon-button"
                type="button"
                aria-label="打开侧栏"
                onClick={onToggleCollapsed}
              >
                <PanelLeftOpen size={18} strokeWidth={2.1} />
              </button>
            ) : null}

            <button
              className="icon-button"
              type="button"
              aria-label="新建对话"
              onClick={onNewConversation}
            >
              <Plus size={18} strokeWidth={2.2} />
            </button>
            {!collapsed ? (
              <button
                className="icon-button"
                type="button"
                aria-label="收起侧栏"
                onClick={onToggleCollapsed}
              >
                <PanelLeftClose size={18} strokeWidth={2.1} />
              </button>
            ) : null}

            {collapsed ? (
              <button
                className="icon-button"
                type="button"
                aria-label="搜索"
                onClick={onOpenSearch}
              >
                <Search size={17} strokeWidth={2} />
              </button>
            ) : null}
          </div>
        </div>

        {!collapsed ? (
          <label className="sidebar-search">
            <Search size={15} className="sidebar-search-icon" />
            <input
              ref={searchInputRef}
              type="search"
              placeholder="搜索对话"
              value={query}
              onChange={(event) => onChangeQuery(event.target.value)}
            />
          </label>
        ) : null}
      </div>

      {!collapsed ? (
        <div className="sidebar-list" aria-label="历史对话">
          {historyFailureDiagnostic ? (
            <div className="diagnostic-shell sidebar-diagnostic-shell">
              <div className="diagnostic-header">
                <div>
                  <p className="diagnostic-kicker">历史恢复</p>
                  <h3>{historyFailureDiagnostic.title}</h3>
                </div>
                {historyFailureDiagnostic.errorCode ? (
                  <span className="diagnostic-tag">{historyFailureDiagnostic.errorCode}</span>
                ) : null}
              </div>
              <p className="diagnostic-message">{historyFailureDiagnostic.message}</p>
              {historyFailureDiagnostic.details.length > 0 ? (
                <ul className="diagnostic-list">
                  {historyFailureDiagnostic.details.map((detail) => (
                    <li key={detail}>{detail}</li>
                  ))}
                </ul>
              ) : null}
              <div className="diagnostic-actions">
                {historyFailureDiagnostic.actions.map((action) =>
                  action.kind === "reload-history" ? (
                    <button
                      key={action.kind}
                      className="diagnostic-action"
                      type="button"
                      onClick={onReloadHistory}
                      disabled={action.disabled}
                    >
                      {action.label}
                    </button>
                  ) : null,
                )}
              </div>
            </div>
          ) : historyError ? (
            <div className="sidebar-recovery">
              <p className="sidebar-error">{historyError}</p>
              <button
                className="sidebar-recovery-button"
                type="button"
                onClick={onReloadHistory}
              >
                重新加载历史
              </button>
            </div>
          ) : null}
          {historyLoading ? <p className="sidebar-note">加载中...</p> : null}
          {!historyLoading && items.length === 0 ? <p className="sidebar-note">暂无历史</p> : null}
          {items.map((item) => {
            const active = item.kind === "session" && item.contentContextId === activeContextId;
            return (
              <button
                key={item.key}
                className={`sidebar-item ${active ? "is-active" : ""}`}
                type="button"
                onClick={() => onSelectItem(item)}
                title={item.subtitle}
              >
                {item.title}
              </button>
            );
          })}
        </div>
      ) : null}

      <div className="sidebar-bottom">
        <div className="sidebar-divider" />
        <button
          className="settings-row"
          type="button"
          onClick={onOpenSettings}
          aria-label="打开设置"
        >
          <Settings size={15} />
          {!collapsed ? <span>设置</span> : null}
        </button>
      </div>
    </aside>
  );
}
