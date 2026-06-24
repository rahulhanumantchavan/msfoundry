https://helloworld-a2a-agent.azurewebsites.net/.well-known/agent-card.json

Create Prompt Agent From UI

![alt text](image-1.png)

Use Prompt agent created from UI
![alt text](image-2.png)

Copied PROJECT_ENDPOINT from Foundry home page and Ran prompt_agent.py to create Foundry Prompt Agent
![alt text](image.png)

Use Prompt agent created from Code
![alt text](image-3.png)

Connect to the agent from outside
Run Chat_with_the_agent.py
![alt text](image-4.png)

Prompt Agent Access any user?
All users added with minimum role of "Foundry User" at project level will be able to access all Prompt Agents in Foundry project.

Prompt Agent Access any Group?
Foundry Support access at project level i.e. minimum role of "Foundry User" at project level can be assigned to AD Group be able to access all Prompt Agents in Foundry project. No segeregation within Foundry project.

Verify if technical account like SPN or UAMI can access prompt agent?
To allow a Service Principal (SP) or User-Assigned Managed Identity (UAMI) to access/invoke your prompt agent in Microsoft Foundry, assign the appropriate RBAC role (typically Foundry User) to that identity at the right scope.

Verify Observability 
Agent Tracing is preview features currently and requires Application Insights
https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept
https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup

Server-side traces in the Foundry portal
Foundry automatically logs server-side traces for Prompt agents, Host agents, and workflows in the Foundry portal. Once tracing is enabled in your Foundry project, you'll have access to out-of-the-box traces for the past 90 days.

https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup#server-side-traces-in-the-foundry-portal


Hosted Agent:
https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-framework#hosted-agents-deployed-to-foundry

