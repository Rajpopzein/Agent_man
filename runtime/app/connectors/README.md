# Connector adapters

Connectors are external service integrations that stay separate from agent
prompts and the generic tool registry.

## Rules

1. Keep secrets in the existing SecretStore. Never put API keys or tokens in
   connector metadata, agent context, SKILL.md content, events, or tool results.
2. Add a connector type to `registry.py`.
3. Implement provider-specific actions in a dedicated adapter module.
4. Give each action an explicit risk level such as read, write, network, or
   destructive.
5. Route network or transactional actions through normal runtime permission and
   approval gates.
6. Return structured, minimal results to agents.
7. Add contract tests before enabling the adapter.

## Groww template

The built-in `groww` entry is intentionally metadata-only. It does not invent
endpoints, authentication, portfolio schemas, trading actions, or order APIs.

To make it live, provide the documented Groww API/authentication contract and
then implement only the actions you want Agent Man to access. Read-only account
or portfolio actions should be separated from any order/trading actions so they
can have different approval policies.
