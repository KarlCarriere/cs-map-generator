<!--
  Stack-specific (Node.js / Vite / Vitest / Playwright tooling).
  Consumed only by the framework-specific project-initiator agent
  (FE::PROJECT-INITIATOR::REACT). Other framework initiators should
  ship their own gitignore template.
-->

# Logs
logs
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*
pnpm-debug.log*
lerna-debug.log*

node_modules
dist
dist-ssr
*.local

# Editor directories and files
.vscode/*
!.vscode/extensions.json
.idea
.DS_Store
*.suo
*.ntvs*
*.njsproj
*.sln
*.sw?

.github/
.vscode/mcp.json
.vite/
features/*
plans/*
specs/*
test-results/*
.claude/
CLAUDE.MD
.mcp.json