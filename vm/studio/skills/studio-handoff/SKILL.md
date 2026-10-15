---
name: studio-handoff
description: "How {{CHIEF}} hands work for {{OWNER}}'s page \"{{STUDIO}}\" (raw clips, overlay lines, planned posts) to the Content Director and what to tell {{OWNER}} afterwards. Load when {{OWNER}} asks about the page, his clips, his overlay lines, his queue, what is posted next, or says plan or make the next posts."
version: 1.0.0
author: agent-automation starter kit
metadata:
  hermes:
    tags: [Content, Team, Kanban, Delegation]
    related_skills: [team-lead, content-studio]
---

# Studio handoff

{{OWNER}}'s page "{{STUDIO}}" has its own small team that works only on the board: the **Content Director** (`contentdirector`) leads, with a Clip Curator, an Overlay Copywriter and a
Video Editor under it. You never talk to the workers: you give the Content Director one card and read its answer. {{OWNER}} does the rest in the **{{STUDIO}}** page of the dashboard:
he uploads clips, approves lines, adds sounds, and approves each finished post before anything goes anywhere. The team never posts to TikTok.

## When {{OWNER}} asks

| He says | You do |
|---|---|
| "plan the next posts", "make this week's posts", "the queue is empty" | one card to `contentdirector`: `kanban_create(assignee="contentdirector", tenant="studio", workspace_kind="dir", workspace_path="/data/studio", idempotency_key="plan-<YYYYMMDD-HH>", max_runtime_seconds=5400, body='{"schema":"xo.card/1","stage":"direct","task":"plan","summary":"<his words>","args":[]}')`. Then tell him one line: it is on the board; the posts will be waiting for his approval in the dashboard |
| "what's next?", "what's in the queue?" | read `/data/tools/studio/cy queue` yourself (it is read only) and say the next two or three posts: the day, the line, which clip |
| "write some new lines" | one card to `overlaycopywriter`: stage `write`, task `write`, idempotency key `write-<YYYYMMDD-HH>`, max runtime 900; tell him the new lines wait for his yes in the dashboard |
| anything about approving, posting, skipping, uploading or the sounds | point him to the **{{STUDIO}}** page; you cannot do those |

When the Content Director's answer comes back, say what it says in plain words: how many posts are planned and waiting, the next day, and anything that ran out (clips, lines or sounds, with what to do about it: upload more clips, approve more lines, add more sounds).

## Rules

* Never approve, deliver, post or skip anything; never write a line's final wording; never add a sound. Those are {{OWNER}}'s.
* Nothing from the page leaves the server except what {{OWNER}} himself posts.
