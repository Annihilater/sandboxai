# Sandbox Web Terminal

A modern web terminal interface for interacting with sandboxed environments, built with Next.js, React, and TailwindCSS.

## Features

- **Modern UI**: Built with Next.js 14, React 18, and TailwindCSS/shadcn-ui components
- **Interactive Terminal**: Full-featured terminal emulation using xterm.js
- **Sandbox Management**:
  - Create new sandboxes with one click
  - List and select from existing sandboxes
  - Real-time status indicators for sandbox states
- **Command Execution**:
  - Support for both shell commands (prefixed with `!`) and IPython commands
  - Real-time command output streaming via WebSocket
  - Command history with up/down arrow navigation
- **Debug View**: Real-time logging of system events and WebSocket messages

## Prerequisites

- Node.js v18 or higher
- pnpm (recommended) or npm
- A running instance of the Sandbox Runtime service (default: http://localhost:5266)

## Getting Started

1. **Install Dependencies**:
   ```bash
   pnpm install
   ```

2. **Configure Environment**:
   Create a `.env.local` file in the project root:
   ```
   MENTIS_RUNTIME_API_URL=http://localhost:5266
   ```

3. **Start Development Server**:
   ```bash
   pnpm dev
   ```

4. **Access the Application**:
   Open [http://localhost:3000](http://localhost:3000) in your browser.

## Usage

1. **Create or Select a Sandbox**:
   - Click "Create New Sandbox" to create a new sandbox environment
   - Or select an existing sandbox from the dropdown list

2. **Terminal Commands**:
   - For shell commands, prefix with `!` (e.g., `!ls -la`)
   - For IPython commands, type directly (e.g., `print("Hello World")`)
   - Use up/down arrow keys to navigate command history

3. **Debug Information**:
   - Check the debug view at the bottom for system events and WebSocket messages
   - Monitor sandbox connection status in real-time

## Project Structure

```
web_demo/
├── app/
│   ├── page.tsx              # Main page UI
│   └── api/                  # API routes for sandbox operations
├── components/
│   ├── ui/                   # shadcn/ui components
│   ├── TerminalComponent.tsx # Terminal implementation
│   └── DebugView.tsx        # Debug log viewer
└── lib/
    └── utils.ts             # Utility functions
```

## Technology Stack

- **Frontend**:
  - Next.js 14
  - React 18
  - TailwindCSS
  - shadcn/ui components
  - xterm.js for terminal emulation

- **Communication**:
  - WebSocket for real-time updates
  - REST APIs for sandbox management
  - Next.js API routes for backend communication

## Development

- The application uses Next.js App Router
- TailwindCSS for styling with shadcn/ui components
- WebSocket connection for real-time terminal interaction
- API routes in Next.js for proxying requests to the backend

## Notes

- Ensure the Sandbox Runtime service is running before starting the application
- The terminal supports both shell and IPython commands
- WebSocket connections are automatically managed based on sandbox selection
- The UI is responsive and supports both light and dark themes 