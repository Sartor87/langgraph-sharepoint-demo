workspace "SharePoint Audit Agent" "C4 model (Context + Container) for the LangGraph-based SharePoint document audit system." {

    # NOTE ON SYNTAX CONFIDENCE: the !docs/!adrs directives below embed the
    # DOCs/ and ADRs/ folders as Structurizr's "Documentation" and "Decisions"
    # tabs. This is a real Structurizr feature, but the exact directive
    # placement/syntax was not verified against a live Structurizr CLI/Lite
    # instance in this environment (none was available) — verify against the
    # actual Structurizr version in use before treating this as final; the
    # model/views/relationships above this note are the well-established,
    # high-confidence part of this file.
    !docs DOCs
    !adrs ADRs

    model {
        auditor = person "Compliance Officer" "Submits SharePoint audit requests and reviews the resulting reports." "Person"

        auditSystem = softwareSystem "SharePoint Audit Agent" "Multi-agent LangGraph workflow that audits SharePoint document libraries for compliance, tracking EU AI Act Annex III traceability requirements." {

            auditAgent = container "Audit Agent" "4-agent Corrective-RAG workflow (search, evaluate, finalize, Fabric context) with a bounded retry loop. The same container image is deployed to two parallel targets — Azure Container Instances and an Azure AI Foundry Hosted Agent — distinguished at runtime by the FOUNDRY_PROJECT_ENDPOINT environment variable, not by which image is built." "Python, LangGraph, FastAPI / Foundry Responses protocol host, Docker" "Container"

            sharepointFunction = container "SharePoint Search Function" "Searches SharePoint document libraries by keyword, and finds files within a library by name pattern, on behalf of the Audit Agent. Authenticates to SharePoint with its own Managed Identity." "C#, Azure Functions (isolated worker), PnP Core SDK" "Container"

            checkpointDb = container "Checkpoint Database" "Stores LangGraph checkpoints for durable state. Used by the ACI deploy target only — the Foundry target keeps state in memory, since Foundry's managed runtime cannot reach this private-VNet-only database." "Azure Database for PostgreSQL Flexible Server 16" "Container,Database"

            secretsStore = container "Secrets Store" "Holds the Audit Agent's runtime secrets: the checkpoint database password, the Azure OpenAI key, and the Application Insights connection string." "Azure Key Vault" "Container"

            containerRegistry = container "Container Registry" "Stores the Audit Agent's built container image; pulled by both deploy targets at deployment time." "Azure Container Registry" "Container"

            jumpbox = container "Admin Jumpbox" "SSH bastion — the only path for a human operator to reach the private Checkpoint Database directly (e.g. to run psql or a migration)." "Ubuntu 22.04, Azure Virtual Machine" "Container"

            observability = container "Observability" "Collects telemetry and logs from the Audit Agent and the SharePoint Search Function." "Azure Application Insights / Log Analytics" "Container"
        }

        sharepointOnline = softwareSystem "SharePoint Online" "The Microsoft 365 document libraries being audited." "External System"
        azureOpenAI = softwareSystem "Azure OpenAI / AI Foundry" "Hosted LLM completions (GPT-4.1) used by all four agents." "External System"
        fabricMcp = softwareSystem "Microsoft Fabric MCP Server" "Microsoft's remote MCP server, exposing a read-only Fabric catalog/workspace tool set." "External System"

        # Relationships
        auditor -> auditAgent "Submits audit requests to, and reviews reports from" "HTTPS/JSON (Responses API or /invoke)"

        auditAgent -> sharepointFunction "Searches documents and finds files via" "HTTPS/JSON"
        sharepointFunction -> sharepointOnline "Queries document libraries from" "PnP Core SDK over REST, Managed Identity auth"

        auditAgent -> checkpointDb "Persists LangGraph checkpoints to (ACI target only)" "PostgreSQL wire protocol over TLS"
        auditAgent -> secretsStore "Reads runtime secrets from" "HTTPS/REST, Managed Identity auth"
        auditAgent -> azureOpenAI "Generates completions via" "HTTPS/JSON"
        auditAgent -> fabricMcp "Queries read-only Fabric context via (Agent 4; degrades gracefully on failure rather than aborting the audit)" "MCP over HTTPS (streamable_http), Managed Identity auth"

        auditAgent -> containerRegistry "Pulls its container image from" "Docker Registry API over HTTPS (deploy time)"
        jumpbox -> checkpointDb "Forwards an admin SSH tunnel to" "TCP port-forward over SSH"

        auditAgent -> observability "Sends telemetry and logs to" "HTTPS / OpenTelemetry"
        sharepointFunction -> observability "Sends telemetry and logs to" "HTTPS / OpenTelemetry"
    }

    views {
        systemContext auditSystem "SystemContext" {
            include *
            autoLayout lr
            description "System Context diagram for the SharePoint Audit Agent."
        }

        container auditSystem "Containers" {
            include *
            autoLayout lr
            description "Container diagram for the SharePoint Audit Agent."
        }

        styles {
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            element "External System" {
                background #999999
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "Database" {
                shape Cylinder
            }
        }
    }

}
