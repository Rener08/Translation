# YouTube Translator Desktop App — UI Optimization Design Spec

**Date:** 2026-04-18  
**Status:** Draft  
**Related Task:** GUI Redesign for PyQt6 Desktop Application

---

## 1. Overview

Redesign the existing PyQt6 desktop application for YouTube video translation with a modern, minimalist aesthetic that prioritizes readability and usability.

**Key Requirements:**
- Display Chinese translation only (no English source text, no segment timestamps)
- Include chat functionality for content Q&A
- Modern, clean UI (user explicitly requested: "太丑了" / "too ugly")
- Desktop-native feel (not web-based)

---

## 2. Design System

### 2.1 Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `bg-primary` | `#F5F5F7` | Main window background |
| `surface` | `#FFFFFF` | Cards, panels, input backgrounds |
| `accent` | `#007AFF` | Primary buttons, active states, links |
| `accent-hover` | `#0056B3` | Button hover state |
| `success` | `#34C759` | Connected status, success states |
| `error` | `#FF3B30` | Error states, offline status |
| `warning` | `#FF9500` | Warning states |
| `text-primary` | `#1D1D1F` | Headings, primary content |
| `text-secondary` | `#86868B` | Metadata, descriptions, placeholders |
| `text-tertiary` | `#C7C7CC` | Disabled states |
| `border` | `#E5E5EA` | Card borders, dividers |
| `border-light` | `#F2F2F7` | Subtle separators |

### 2.2 Typography

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
```

| Element | Size | Weight | Line Height | Color |
|---------|------|--------|-------------|-------|
| App Title | 20px | 700 (Bold) | 1.2 | text-primary |
| Section Header | 16px | 600 (Semibold) | 1.3 | text-primary |
| Body / Translation | 15px | 400 (Regular) | 1.8 | text-primary |
| Metadata / Labels | 13px | 400 (Regular) | 1.4 | text-secondary |
| Button Text | 14px | 600 (Semibold) | 1.0 | white (on accent) |
| Chat User | 14px | 400 (Regular) | 1.5 | text-primary |
| Chat AI | 14px | 400 (Regular) | 1.5 | text-primary |

### 2.3 Spacing System (8px Grid)

| Token | Value | Usage |
|-------|-------|-------|
| `space-xs` | 4px | Tight spacing (icon + text) |
| `space-sm` | 8px | Default padding inside elements |
| `space-md` | 16px | Card internal padding |
| `space-lg` | 24px | Section separation |
| `space-xl` | 32px | Major section margins |

### 2.4 Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `radius-sm` | 6px | Small buttons, input fields |
| `radius-md` | 10px | Cards, panels |
| `radius-lg` | 12px | Large cards, modals |
| `radius-full` | 9999px | Status badges, pills |

### 2.5 Shadows

| Token | Value | Usage |
|-------|-------|-------|
| `shadow-sm` | `0 1px 2px rgba(0,0,0,0.04)` | Subtle elevation |
| `shadow-md` | `0 4px 12px rgba(0,0,0,0.08)` | Cards |
| `shadow-lg` | `0 12px 24px rgba(0,0,0,0.12)` | Modals, dropdowns |

---

## 3. Layout Structure

### 3.1 Window Configuration

- **Minimum Size:** 1100×750px
- **Default Size:** 1280×800px
- **Resize Policy:** Both dimensions resizable
- **Sidebar Width:** 320px (fixed, non-collapsible)

### 3.2 Main Layout

```
┌─────────────────────────────────────────────────────────────┐
│  ┌──────────────┐  ┌──────────────────────────────────────┐ │
│  │              │  │  Video Info Card                      │ │
│  │   Sidebar    │  │  [Thumbnail] Title + Meta             │ │
│  │   (320px)    │  ├──────────────────────────────────────┤ │
│  │              │  │                                      │ │
│  │  - Header    │  │  Translation Panel                   │ │
│  │  - URL Input │  │  [中文翻译]                           │ │
│  │  - Settings  │  │                                      │ │
│  │  - Status    │  │  Scrollable text area                │ │
│  │  - Button    │  │  with comfortable line height        │ │
│  │              │  │                                      │ │
│  │              │  ├──────────────────────────────────────┤ │
│  │              │  │  Chat Panel                          │ │
│  │              │  │  Messages + Input                    │ │
│  │              │  │                                      │ │
│  └──────────────┘  └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Sidebar (Left Panel)

**Header Section:**
- App icon (placeholder or emoji: 🎬)
- Title: "YouTube 翻译助手"
- Subtitle: "智能视频翻译工具" (optional, 13px, text-secondary)

**URL Input Section:**
- Label: "视频链接" (13px, text-secondary, uppercase tracking)
- Input field with placeholder: "粘贴 YouTube 链接..."
- Icon inside input (🔗) or clear button

**Settings Section (Card):**
- Header: "翻译设置" with settings icon
- Provider dropdown: "翻译服务" label
- Source mode dropdown: "内容来源" label
- API Key input: password field with show/hide toggle
- Model input: text field

**Status Section:**
- Colored dot indicator (8px circle)
- Status text: "已连接" / "离线" / "错误"
- Backend URL display (optional, 12px)

**Action Button:**
- Full-width primary button: "开始处理"
- Loading state: spinner + "处理中..."
- Disabled state: gray background

**Progress Section:**
- Progress bar (thin, 4px height, accent color)
- Status label below: "正在获取视频信息..."

### 3.4 Main Content Area (Right Panel)

**Video Info Card:**
- Horizontal layout: thumbnail (120×80px, 8px radius) + text
- Title: 16px bold, 2-line max with ellipsis
- Metadata: duration, channel name, 13px gray
- Hover: subtle shadow increase

**Translation Panel:**
- Header: "中文翻译" + word count (optional)
- Scrollable text area (QTextEdit, read-only)
- Comfortable line height (1.8)
- No English text, no timestamps, no segment numbers
- Paragraph spacing: 16px between paragraphs
- Placeholder: "翻译内容将显示在这里..."

**Chat Panel:**
- Header: "内容问答" + message count
- Message list (scrollable):
  - User messages: right-aligned, accent background (#007AFF), white text, rounded
  - AI messages: left-aligned, gray background (#F2F2F7), dark text, rounded
  - Avatar placeholders (👤 / 🤖)
  - Timestamp (optional, 12px)
- Input area:
  - Text input with placeholder
  - Send button (icon or text)
  - Disabled when no content loaded

---

## 4. Component Specifications

### 4.1 Input Fields

```
┌──────────────────────────────────────┐
│  Label (13px, text-secondary)        │
│  ┌────────────────────────────────┐  │
│  │  Placeholder text...          │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

- Height: 40px
- Padding: 10px 14px
- Border: 1px solid border (#E5E5EA)
- Border radius: 8px
- Focus: border-color accent + shadow-sm
- Disabled: background border-light, text text-tertiary

### 4.2 Primary Button

```
┌──────────────────────────────────┐
│  开始处理                        │
└──────────────────────────────────┘
```

- Height: 44px
- Padding: 12px 24px
- Background: accent (#007AFF)
- Text: white, 14px semibold
- Border radius: 10px
- Hover: darken 10%, scale(1.01)
- Active: darken 15%
- Disabled: background #C7C7CC, text white
- Transition: all 150ms ease

### 4.3 Cards

```
┌──────────────────────────────────────┐
│                                      │
│  Content area with padding 20px      │
│                                      │
└──────────────────────────────────────┘
```

- Background: surface (#FFFFFF)
- Border: 1px solid border (optional)
- Border radius: 12px
- Shadow: shadow-md
- Hover (interactive): shadow-lg, translateY(-1px)

### 4.4 Chat Messages

**User Message:**
```
                              ┌──────────┐
                              │ 你好     │
                              │ 世界     │
                              └──────────┘
```
- Background: accent (#007AFF)
- Text: white
- Border radius: 18px (top-right: 4px)
- Max width: 80%
- Padding: 10px 16px

**AI Message:**
```
┌──────────┐
│ 你好     │
│ 世界     │
└──────────┘
```
- Background: #F2F2F7
- Text: text-primary
- Border radius: 18px (top-left: 4px)
- Max width: 80%
- Padding: 10px 16px

### 4.5 Progress Bar

- Height: 4px
- Background: border-light
- Fill: accent
- Border radius: 2px
- Animation: smooth width transition

---

## 5. Interaction Design

### 5.1 States

**Initial State:**
- URL input empty or with example URL
- Settings visible with defaults
- Translation area shows placeholder
- Chat area shows welcome message
- Status: checking backend

**Processing State:**
- Button disabled, shows spinner
- Progress bar animates
- Status text updates with stage
- Translation area cleared

**Success State:**
- Button re-enabled
- Video card populated
- Translation displayed
- Chat enabled with welcome message

**Error State:**
- Button re-enabled
- Status shows error
- Error dialog or inline message
- Optional: retry button

### 5.2 Animations

| Animation | Duration | Easing | Trigger |
|-----------|----------|--------|---------|
| Button hover | 150ms | ease | Mouse enter/leave |
| Card hover lift | 200ms | ease-out | Mouse enter/leave |
| Progress fill | 300ms | ease-out | Progress update |
| Message appear | 200ms | ease-out | New message |
| Panel fade | 150ms | ease | Content switch |
| Spinner rotate | 1s | linear | Infinite loop |

### 5.3 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + Enter` | Start processing (when URL focused) |
| `Enter` | Send chat message (when chat focused) |
| `Esc` | Cancel processing |

---

## 6. Responsive Behavior

### 6.1 Width < 1000px
- Sidebar shrinks to 280px
- Content area takes remaining space
- Chat panel height reduces

### 6.2 Width < 800px
- Not recommended (show warning or enforce minimum)
- Alternative: stack sidebar above content

---

## 7. Accessibility

- Color contrast ratio ≥ 4.5:1 for all text
- Focus indicators visible (blue outline)
- Keyboard navigable (Tab order)
- Screen reader labels for icons
- Respect system dark mode (future enhancement)

---

## 8. Implementation Notes

### 8.1 PyQt6 Specifics

- Use `QApplication.setStyle("Fusion")` as base
- Apply stylesheet globally via `setStyleSheet()`
- Use `QScrollArea` for scrollable content
- Use `QSplitter` for resizable panels (optional)
- Thread workers for API calls (already implemented)

### 8.2 Performance

- Lazy load chat history (if grows large)
- Virtual scrolling for long translations (if needed)
- Debounce API calls
- Cache video info

---

## 9. Open Questions

1. Should we support dark mode toggle?
2. Should chat history persist across sessions?
3. Should we show word/character count for translation?
4. Should video thumbnail be clickable (open in browser)?

---

## 10. Acceptance Criteria

- [ ] UI matches color palette and typography
- [ ] Layout follows sidebar + content structure
- [ ] Translation shows Chinese text only
- [ ] Chat displays message bubbles
- [ ] All buttons have hover states
- [ ] Progress bar shows processing stages
- [ ] Status indicator reflects backend state
- [ ] No English segments or timestamps visible
- [ ] Application feels modern and polished
- [ ] User feedback: "Not ugly anymore"

---

**Next Step:** Implementation via `writing-plans` skill
