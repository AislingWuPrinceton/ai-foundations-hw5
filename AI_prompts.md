# AI Prompts — Homework 5: Campus Customs Multi-Agent Operations

This file records the prompts I sent to my vibe coder (Claude Code) for each problem, kept in my original wording.

---

## Problem 1: Vibe coder prompts

### Prompt

> Please create an AI_prompts.md file in my assignment folder to keep a record of the prompts I use during this assignment.
>
> Organize the file with a separate section for each problem, including its number and title. In each section, record at least one prompt I actually send you, preserving my wording.
>
> If I use a follow-up prompt, record it under the same problem and include one sentence explaining what was missing from the first response. Do not invent prompts or follow-ups that I have not used.
>
> Record this prompt under Problem 1, and keep the file updated as we work through the remaining problems. I will describe each task in my own words.

---

## Problem 2: Study the Campus Customs database

### Prompt

> Please help me understand the Campus Customs database before I work on the later problems.
>
> Copy data/campus_customs.db to data/campus_customs_new.db, keeping the original database unchanged. If the working copy already exists, do not overwrite it.
>
> Inspect every table in the database and identify its fields, primary keys, and foreign-key relationships. Examine the three open tickets and explain how each one connects to records in other tables, using the actual data.
>
> Create output/harness.md with a section for each table. List all its fields and add one short sentence explaining why the table is useful for the agents. Also include a concise explanation of the relationships you found while examining the three open tickets. If the document already exists, preserve its contents and add or update the relevant sections.
>
> Use the database as the source of truth, and do not invent fields or relationships. This task is for inspection and documentation; do not change any database records.
>
> Record this prompt under Problem 2 in AI_prompts.md.

---

## Problem 3: Build the MCP server

### Prompt

> Please build a FastMCP server in mcp_server/ that uses data/campus_customs_new.db.
>
> First, review the database schema, tickets 101, 102, and 103, and the existing output/harness.md. Based on what those tickets actually need, implement three clearly named MCP tools that retrieve relevant information from the database. Choose the tools from the real ticket requirements rather than guessing what data or functionality is needed.
>
> Use the actual table names, fields, and relationships. Give each tool clear parameters, a description of its purpose, and understandable results. Do not fabricate data. Handle missing records clearly, and make sure the database path resolves correctly regardless of the directory from which the server is launched.
>
> Extend output/harness.md without removing the existing content. For each of the three tools, document its name, the table or tables it reads, the ticket it helps advance (101, 102, or 103), and one specific sentence explaining how the information it retrieves helps with that ticket. Avoid vague descriptions such as “reads inventory.”
>
> Create a short mcp_server/README.md explaining the server’s purpose, the database file it uses, and its three tools. Include any dependencies needed for the implementation.
>
> This problem only requires the server code and documentation. Do not launch the server, connect it to an agent, or modify database records.
>
> Record this prompt under Problem 3 in AI_prompts.md.

---

## Problem 4: Connect the MCP server and test each tool

### Prompt

> Please connect the MCP server we built in Problem 3 to the AI coding assistant I am using for this project, then test all three tools through that connection.
>
> Inspect the existing server and the assistant’s supported MCP configuration format. Add the project connection settings to .mcp.json at the project root, or to the local MCP configuration location required by this assistant. Preserve any existing server configurations and use the correct executable, server entry point, and paths.
>
> Once connected, confirm that all three tools are available. For each tool, use a clear natural-language request with valid inputs based on the actual database records, and invoke it through the assistant’s MCP connection. Compare the returned values with data/campus_customs_new.db to verify that they match.
>
> Save the evidence in output/mcp_smoke.json as valid JSON. For each tool, include the exact prompt used to request the call, the tool name, the input arguments, and the actual tool output. Also record whether the output matches the database.
>
> Use real MCP calls for the evidence. Do not substitute direct Python function calls or SQL queries for the MCP tests, and do not invent outputs or claim success for calls that did not run. If a connection step requires me to reload the assistant or take another manual action, explain the exact step and continue testing after the connection is available.
>
> Do not modify database records during these tests. Record this prompt and any actual follow-up prompts under Problem 4 in AI_prompts.md.

### Follow-up prompt

> 继续 Problem 4 的 MCP 测试

What was missing: the first response set up the `.mcp.json` connection, but it could not run the three MCP tool tests until the assistant was reloaded and the campus-customs server came online.

---

## Problem 5: Build the agent team and expand the MCP tools

### Prompt

> Please extend the existing Campus Customs project with a PydanticAI team containing five agents: Boss, Inventory, Accounting, Facilities, and Customer Service.
>
> First, review the existing project, database schema, open tickets, MCP server, and documented shop rules. Base the implementation on those sources. Do not invent business rules or shop data; identify any missing rules explicitly.
>
> Configure every agent to use only gpt-6-luna through Portkey, with PORTKEY_API_KEY loaded from the environment. Do not hard-code or log the API key.
>
> Put each agent’s prompt in its own file under backend/prompts/, define shared data types in backend/models.py, and place the agent implementation under backend/. Write detailed, role-specific prompts covering responsibilities, relevant shop rules, tool use, delegation, missing information, and completion criteria.
>
> Implement actual agent execution loops and delegation so every role can delegate to every other role when needed. Pass the ticket context and relevant findings between agents, return structured results, and prevent unlimited delegation cycles.
>
> Connect all agents to the existing MCP server. All shop facts and database operations must go through MCP tools backed by data/campus_customs_new.db. Do not give agents direct database access or create a separate shop-tools layer that bypasses MCP.
>
> Inspect the open tickets and add the MCP tools needed to handle them. Preserve the existing tools. Use real database fields and relationships, validate tool inputs, and handle missing records and errors clearly. For tools that change data, use transactions and guard against duplicate actions.
>
> Implement audit logging to output/audit_trail.json. Preserve existing entries and append records as each agent-loop step occurs, keeping the file valid JSON. Include enough information to trace the run, ticket, agent, delegation, MCP tool calls and arguments, results, errors, and final outcome. Record available token usage without exposing secrets or unnecessary customer information.
>
> Add practical guardrails for customer information and financial actions, and enforce limits on model requests, token usage, tool calls, delegation depth, retries, and run duration. Clearly document which sensitive actions require human approval.
>
> Extend output/harness.md with all five agents, their responsibilities and delegation connections, every MCP tool and the tables it reads or updates, and a short safety section explaining the business safeguards and token limits.
>
> Update mcp_server/README.md so its tool list matches the final implementation.
>
> Verify the MCP integration, delegation, audit-log preservation, and enforced limits with focused tests. Keep test changes isolated from the assignment database, and report any live checks that could not be completed.
>
> Record this prompt and any actual follow-up prompts under Problem 5 in AI_prompts.md.

---

## Problem 6: Plan the three tickets

### Prompt

> Please create output/desk_tickets.html to document the expected handling of tickets 101, 102, and 103 before we connect the backend or run the agent team.
>
> Review the actual ticket details through the existing MCP tools, along with the agent roles, prompts, shop rules, and available MCP tool definitions. Use this information to make a specific plan for each ticket. Do not invent ticket details, business rules, or tool names.
>
> Build a self-contained HTML page that opens by double-clicking, without requiring a web server or backend connection. Include five working tabs: Ticket 101, Ticket 102, Ticket 103, Cash, and Reflection. Keep the Cash and Reflection tabs blank or show a short “Coming later” note.
>
> For each ticket tab, fill only an Expected section containing:
>
> 1. The first agent Boss should call and a specific reason for choosing that agent.
> 2. Every expected delegation, showing who delegates to whom, in what order, and for what purpose. Include specialist-to-specialist delegations where the ticket requires them, and identify any conditional branches.
> 3. The exact MCP tools expected to be used, which agent will use each tool, and what information or action it provides for that ticket.
>
> Choose only the specialists needed for each ticket. Avoid

### Follow-up prompt

> Sorry，给你完整版：
>
> problem6: Plan the three tickets
> Please create output/desk_tickets.html to document the expected handling of tickets 101, 102, and 103 before we connect the backend or run the agent team.
> Review the actual ticket details through the existing MCP tools, along with the agent roles, prompts, shop rules, and available MCP tool definitions. Use this information to make a specific plan for each ticket. Do not invent ticket details, business rules, or tool names.
> Build a self-contained HTML page that opens by double-clicking, without requiring a web server or backend connection. Include five working tabs: Ticket 101, Ticket 102, Ticket 103, Cash, and Reflection. Keep the Cash and Reflection tabs blank or show a short “Coming later” note.
> For each ticket tab, fill only an Expected section containing:
>
> 1. The first agent Boss should call and a specific reason for choosing that agent.
> 2. Every expected delegation, showing who delegates to whom, in what order, and for what purpose. Include specialist-to-specialist delegations where the ticket requires them, and identify any conditional branches.
> 3. The exact MCP tools expected to be used, which agent will use each tool, and what information or action it provides for that ticket.
>
> Choose only the specialists needed for each ticket. Avoid generic plans where Boss calls everyone or all five agents participate in every ticket.
> Add an empty Actual section to each ticket tab with space for later results. Clearly label the Expected content as a prediction, not an observed execution.
> Use a readable layout and make the tab controls work locally. Do not run the agent team, resolve tickets, change database records, or populate the Actual sections for this problem.
> Record this prompt under Problem 6 in AI_prompts.md.

What was missing: my first paste was cut off after "Avoid", so the first page had no empty Actual sections and did not label the Expected plans as predictions.

---

## Problem 7: Build the backend routes

### Prompt

> Please implement the FastAPI backend in backend/main.py for the React dashboard we will build next.
> Review the existing PydanticAI team, MCP server, database schema, and audit logging before making changes. Reuse the existing implementation and keep shop-data reads and writes going through MCP. Add MCP tools if the required backend operations are not yet supported.
> Implement routes that:
>
> 1. Return tickets 101, 102, and 103 with their current open or resolved status.
> 2. Accept a ticket ID and run the existing agent team on that ticket.
> 3. Return recent agent events, including agent messages, delegations, tool names, and tool results, so the dashboard can refresh. Support incremental retrieval with a cursor or event ID.
> 4. Approve a prepared payment or purchase only after an explicit human approval request from the dashboard. Agents may prepare a pending action, but they must not execute it or change cash themselves.
> 5. Return the current checking-account balance from cash_accounts.
> 6. Reset data/campus_customs_new.db to the original values in data/campus_customs.db for a fresh run, preserving the original database and existing audit history.
>
> Use clear HTTP methods, validated request and response models, and useful error responses. Prevent overlapping runs on the same ticket and return a run identifier and status if processing happens in the background.
> For approvals, accept the identifier of a stored pending action and validate its status, amount, and related records on the server. Apply the approved operation through MCP in a transaction, prevent duplicate execution, and record the approval and resulting changes in the audit trail. Do not treat agent-generated approval as human approval.
> Make reset an explicit action. Prevent it while agent runs or financial operations are active, clear stale pending actions and run state as appropriate, and append a reset event without erasing audit records.
> Configure local frontend access as needed. Ensure the backend can start from the backend/ directory with:
> uvicorn main --reload --port 8000
> Extend output/harness.md with one line per route showing its HTTP method, URL, and purpose. Document how to start the server.
> Test the routes and financial safeguards using an isolated database copy. Start the backend on port 8000 and verify its availability, but do not resolve the assignment tickets, approve real pending actions, or reset the assignment database merely to test the routes. Report any checks that could not be completed.
> Record this prompt and any actual follow-up prompts under Problem 7 in AI_prompts.md.

---

## Problem 8: Build the agent dashboard

### Prompt

> Please build a polished Campus Customs dashboard in frontend/ using React, Vite, and TypeScript. Connect it to the existing FastAPI backend from Problem 7 at http://localhost:8000.
> Inspect the existing backend routes and response models first, and use their actual API contracts. Display real backend data rather than fabricated tickets, messages, balances, or results.
> The dashboard must:
>
> 1. List tickets 101, 102, and 103 with their current status.
> 2. Let me select one ticket and explicitly start the agent team on it.
> 3. Show the five agents—Boss, Inventory, Accounting, Facilities, and Customer Service—and display their messages, actions, delegations, and MCP tool activity as the run progresses.
> 4. Refresh ticket status after processing and mark a ticket resolved when the backend confirms it is resolved. Do not assume that a finished or failed run means the ticket is resolved.
> 5. Show a short, evidence-based summary of what each participating agent did on the selected ticket.
> 6. Display pending payments or purchases with their purpose, amount, related ticket, and an explicit human Approve button connected to the backend approval route.
> 7. Display the current checking balance from the backend and refresh it after a successful approval.
>
> Use incremental event polling or the backend’s existing streaming mechanism. Keep events associated with the correct ticket and run, avoid duplicate events, and stop unnecessary polling when appropriate. Handle loading, empty states, connection errors, failed runs, and approval errors clearly. Prevent duplicate run starts and duplicate approval submissions.
> Give the interface a distinctive, coherent design that feels like a useful shop operations desk. Include a ticket list, a prominent selected-ticket workspace, clearly differentiated agent panels, a readable activity feed, and a visible cash and approval area. Distinguish agents with names, role labels, and visual styling; do not rely on color alone. Make the layout responsive and keyboard accessible.
> Keep approvals manual. Do not automatically approve actions, change the displayed balance before backend confirmation, or run tickets on page load.
> Configure the backend to allow the frontend origin, normally http://localhost:5173. Make the frontend API base URL configurable, defaulting to http://localhost:8000. Ensure the frontend starts from frontend/ with npm run dev.
> Write output/design.md explaining the final layout, how agents are distinguished, how resolved tickets and cash are presented, and the reasons for the creative design choices.
> Run the TypeScript checks and production build, then inspect the dashboard in a browser with the backend connected. Verify interactive flows using isolated test data where changes are required. Do not resolve assignment tickets or approve pending payments merely to test the interface. Report any verification that could not be completed.
> Record this prompt and any actual follow-up prompts under Problem 8 in AI_prompts.md.

---

## Problem 9: Resolve the three tickets and document the results

### Prompt

> Please carry out a complete, evidence-based run of tickets 101, 102, and 103 using the existing React dashboard, FastAPI backend, PydanticAI agent team, and MCP server.
> Before starting, check that no runs or financial operations are active. Reset data/campus_customs_new.db to the original values through the existing reset operation, preserve the original database and audit history, and record the starting checking balance after the reset.
> Run each ticket from the React dashboard until it is genuinely resolved. Use the actual agents and MCP tools. Do not replace the workflow with direct SQL updates, manually mark tickets resolved, or fabricate agent activity. If implementation problems prevent progress, fix them and retry without duplicating completed actions or payments.
> When a payment or purchase requires approval, present the pending action and its amount to me and wait for me to approve it through the dashboard. Do not approve on my behalf or bypass the human-approval requirement. Continue processing after approval.
> Append all real agent steps, delegations, MCP calls, errors, retries, and human approval events to output/audit_trail.json without deleting existing records. Identify this full run clearly so its evidence can be distinguished from earlier tests.
> Update output/desk_tickets.html:
>
> * Preserve each ticket’s original Expected section.
> * Fill its Actual section using this run’s evidence, including participating agents, actual delegations, MCP tools used, and the outcome.
> * In the Cash tab, show the starting checking balance, each ticket’s itemized cash changes with the payment or purchase identifier, purpose, and dollar amount, and the ending checking balance.
> * Explicitly show when a ticket has no cash change.
> * Reconcile the starting balance plus all signed cash changes with the ending balance, and verify that the ending balance matches cash_accounts in the working database.
>
> Save output/resolved_tickets.json as valid JSON. For each ticket, include its ID, verified final status, a short outcome, each participating agent’s contribution, and any human approvals with their related action identifiers and amounts.
> Capture a real screenshot of the React dashboard showing each resolved ticket—101, 102, and 103—and create output/resolved_board.html to display those screenshots. Make the page viewable by double-clicking, with screenshots embedded or stored at reliable relative paths. Do not use mockups or generated images as evidence.
> Finish output/harness.md so it accurately documents the database tables, all current MCP tools, the five agents, API routes, dashboard, and safety rules.
> Finally, verify that all three tickets are resolved in the working database, all required files are present, the screenshots show the actual resolved states, and the cash figures reconcile. Report the final ticket statuses, starting and ending checking balances, itemized cash changes, and any unresolved issues.
> Record this prompt and any actual follow-up prompts under Problem 9 in AI_prompts.md.

### Follow-up prompt

> 先不要替我选择。请说明这四个确认问题分别对应哪个工单，哪些答案由数据库或已有店铺规则决定，哪些需要我人工裁量。对于有依据的问题，请列出相关表、字段、记录或规则来源；对于没有政策的问题，请说明选项的影响。不要把缺失的政策当成已有规则，也不要把建议当成标准答案。

What was missing: the first response asked me to choose answers (with options marked "Recommended") without explaining which ticket each question belonged to, which parts the database or documented rules already decide, and what each undocumented choice would change.

### Follow-up prompt

> 好的，那你像之前那样问我吧

What was missing: the explanation answered which ticket each question belonged to and what the evidence covered, but my four decisions still had not been collected in the same multiple-choice format as before.

### Follow-up prompt

> Approve $840.00 or Reject.告诉我这俩行为区别在哪

What was missing: the response asked me to approve or reject pending action #1 without explaining what each choice would change in the database, cash, and later tickets.

### Follow-up prompt

> 已批准

What was missing: the run was paused until I approved pending action #1 ($840 invoice payment) on the dashboard.

### Follow-up prompt

> 已批准

What was missing: ticket 101 could not close until I approved pending action #2 ($8 restock purchase) on the dashboard.

### Follow-up prompt

> 已批准

What was missing: ticket 102 could not continue until I approved pending action #3 ($2,400 rent payment) on the dashboard.

### Follow-up prompt

> 已批准

What was missing: ticket 103 could not close until I approved pending action #4 ($264 restock purchase) on the dashboard.

---

## Problem 10: Reflect on the agent team’s performance

### Prompt

> Please help me develop and add a detailed, evidence-based reflection to the Reflection tab in output/desk_tickets.html.
> First, review the preserved Expected plans, the Actual sections for tickets 101, 102, and 103, the Cash tab, output/resolved_tickets.json, the relevant audit-trail entries, and the implemented agents and MCP tools. Distinguish predictions, observed results, and hypothetical future scenarios.
> Cover all five questions:
>
> 1. Evaluate the agents’ performance on each ticket separately. Explain what worked well and what did not, using concrete evidence about task completion, delegations, tool use, errors, human approvals, and cash accuracy. Use efficiency metrics only when they were actually recorded.
> 2. Compare Expected with Actual for each ticket. Identify differences in the first specialist called, delegation order, participating agents, and MCP tools used. Explain the consequences of those differences, and clearly label any inferred explanations.
> 3. Identify specific parts of this application that would have been simpler with one agent using tools. Explain which coordination steps could be removed and what tradeoffs would remain, based on the observed runs.
> 4. Describe exactly three plausible new Campus Customs problems that the current team could solve with the tools already implemented. For each, identify the relevant agents, exact existing MCP tool names, required data, and any human approval needed. Do not assume capabilities that the tools do not have.
> 5. Describe exactly three plausible new problems that the current implementation could not fully solve. For each, explain the capability gap and the additional tools, data sources, agent roles, or human expertise needed. Do not implement those additions for this problem.
>
> Tie every answer to this application and the three completed tickets. Refer to the ticket and Cash tabs as evidence, and add working internal links where useful. Avoid generic claims about multi-agent AI.
> Write in clear, natural English. Do not invent my personal experiences, opinions, or lessons learned. If my own judgment is needed and cannot be inferred from the evidence, ask me focused questions, then incorporate my answers.
> Preserve all existing Expected, Actual, and Cash content. If evidence is missing or contradictory, identify the gap rather than inventing an explanation or result.
> Check that all five questions are answered, all six future scenarios are clearly identified, and the Reflection tab works when the HTML file is opened locally.
> Record this prompt and any actual follow-up prompts under Problem 10 in AI_prompts.md.

### Follow-up prompt

> 开始做 Problem 10 的反思

What was missing: the first response could not write the reflection because Problem 9's run had not finished and the Actual, Cash, and resolved_tickets.json evidence did not exist yet, so I asked it to start once that evidence was in place.

---

## Problem 11: Prepare and submit the project to GitHub

### Prompt

> Please prepare this completed Campus Customs assignment for submission and push it to a public GitHub repository.
> Inspect the existing project and Git configuration first. Use the intended assignment repository if one is already configured. If the repository destination is unclear, ask me for the GitHub owner and repository name before publishing.
> Check that the project contains:
>
> * AI_prompts.md, requirements.txt, .env.example, .gitignore, .mcp.json, and README.md.
> * Both data/campus_customs.db and data/campus_customs_new.db.
> * The MCP server implementation and its README.
> * The React frontend and FastAPI backend.
> * backend/models.py and separate prompt files for Boss, Inventory, Accounting, Facilities, and Customer Service.
> * All required output files: harness.md, mcp_smoke.json, desk_tickets.html, design.md, resolved_tickets.json, resolved_board.html, audit_trail.json, and github_url.txt.
> * Any screenshot files required by resolved_board.html.
>
> Preserve the original database, the completed working database, and all genuine run evidence. Do not reset the working database during submission preparation or fabricate missing deliverables. Identify and fix ordinary packaging issues, and report any missing evidence that requires an actual run.
> Ensure the real .env, API keys, credentials, local virtual environments, node_modules, and temporary files are excluded from Git. Include a safe .env.example with placeholder values. Inspect the files to be published and the Git history for accidentally committed secrets without printing secret values. If a secret is found in history, stop publication and explain the remediation needed.
> Make the project portable for graders. Remove unnecessary machine-specific paths from shared configuration, preserve the frontend dependency lockfile, and ensure requirements.txt includes the Python dependencies needed to run the app.
> Update the root README.md with clear setup instructions, environment-variable configuration, MCP startup and connection steps, FastAPI startup, React startup, and instructions for copying the original database to the working copy or using the reset route before a fresh three-ticket run. Explain that resetting replaces the completed working state.
> Run appropriate packaging checks and verify that the saved HTML pages and their screenshots work locally.
> Create or use the intended public GitHub repository, save its actual URL in output/github_url.txt, commit the completed submission files, and push them. Ensure github_url.txt itself is included in the pushed commit.
> Verify that the repository is public and that the required files, including both databases and output evidence, are available remotely. If possible, check the submission from a fresh clone.
> Record this prompt and any actual follow-up prompts under Problem 11 in AI_prompts.md before the final commit.
> Return the public repository URL and the verification results. I will submit the URL to Canvas myself.
