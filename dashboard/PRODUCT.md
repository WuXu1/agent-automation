# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Vite + React 19 + TypeScript, Tailwind CSS v4, React Three Fiber (three, drei, postprocessing), Motion, Lucide. Served as a
prebuilt static bundle by a small standard-library Python bridge on the VM (`bridge/`).

## Users

One person who runs a Hermes crew (a chief of staff and three specialists) on one small VM. They open it on a laptop or a
phone, over their own Tailscale network, to check that everything is healthy, what the agents remember, how long the
credit lasts and what the agents are working on. Many are new to AI agents: plain words, money impact stated.

## Product Purpose

One place for the whole setup: the Mem0 memory (the "second brain"), the agents and their tools, the VM and its money, the
task board and the optional add-ons. Success: the owner finds any state in seconds and can correct a memory without a terminal.

## Positioning

It shows the owner's own live system, not a generic AI console. Every name comes from `crew.json`; demo mode (made-up data
for an owner called Sam) shows everything working before the bridge is installed.

## Operating Context

Every service listens on the VM's loopback only: Hermes gateway `127.0.0.1:8642`, Mem0 `8888`. The bridge (`127.0.0.1:8890`)
reads them and is published tailnet-only with `tailscale serve`; the page calls it at the same origin (`/api`).

## Capabilities and Constraints

- Read: system gauges, services, backup result, agents and their MCP servers, skills and automations, the board, all
  memories, semantic search, Gmail (read only, add-on), every sign-in and balance.
- Write, each behind a confirm step: Mem0 notes and pins, the brain's sections and check-up fixes, agent profiles, skills and
  MCP servers, cron jobs, board cards, Brief the chief, a quiet gateway restart (root helper) and Backup now (add-on). Never
  Mem0 reset or configure, never sending mail. Agents are added and moved through Claude, not the page.
- No keys in the bundle; the page sees where a secret lives, never its value.
- The Azure credit has no API on a student subscription: the owner types a dated figure.

## Brand Commitments

Name: **Command Center**. Colour meanings are fixed (cyan memory, violet agents and priority, emerald healthy, amber runway and
limits, red errors and hard caps).

## Evidence on Hand

Demo data must stay invented: no real memory text, contacts, numbers, emails, addresses or ids.

## Product Principles

1. State first: every number is live or plainly marked demo, with its age.
2. One meaning per colour, everywhere.
3. Edits are deliberate and reversible: confirm before a write, show what changed.
4. Almost free to run: no servers of its own beyond the bridge, no telemetry, only pennies of DeepSeek for the AI jobs.
