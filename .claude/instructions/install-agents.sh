#!/bin/sh
if [ -z "$NODE_AUTH_TOKEN" ]; then
  printf "\n***\n*** Note: @devsights/frontend-agents has not been installed. This is OK — it just means the Devsights development AI agents have not been added. It does not affect anything.\n***\n\n"
else
  npx --yes @devsights/frontend-agents
fi
