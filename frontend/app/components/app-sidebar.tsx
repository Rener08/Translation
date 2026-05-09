import { PanelLeftClose, PanelLeftOpen, Plus, Search, Settings } from "lucide-react";
import type { RefObject } from "react";

import { SidebarListItem } from "../hooks/use-session-history";


type AppSidebarProps = {
  collapsed: boolean;
  query: string;
  activeContextId: string;
  historyLoading: boolean;
  historyError: string;
  items: SidebarListItem[];
  searchInputRef: RefObject<HTMLInputElement | null>;
  onToggleCollapsed: () => void;
  onOpenSearch: () => void;
  onNewConversation: () => void;
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
  items,
  searchInputRef,
  onToggleCollapsed,
  onOpenSearch,
  onNewConversation,
  onOpenSettings,
  onChangeQuery,
  onSelectItem,
}: AppSidebarProps) {
  return (
    <aside className={`app-sidebar ${collapsed ? "is-collapsed" : ""}`}>
      <div className="sidebar-top">
        <div className="sidebar-title-row">
          {!collapsed ? <h1 className="sidebar-title">YouTube 翻译助手</h1> : null}
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
          {historyError ? <p className="sidebar-error">{historyError}</p> : null}
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
