## Problem, Team, and Overview of Experiments

### Problem Statement

Modern cloud-first companies increasingly rely on Infrastructure-as-Code (IaC) to define and manage production infrastructure. As the size and complexity of Terraform codebases grow, keeping them continuously compliant with security and privacy frameworks (e.g., SOC 2, ISO 27001) becomes both operationally expensive and error-prone. Existing tools such as Delve attempt to remediate compliance failures directly in AWS by automatically mutating live resources. While this can close gaps quickly, it introduces serious problems for security and platform teams:

- **Permission Hardening Nightmare**: Granting automated agents broad write access to production AWS accounts violates least-privilege principles and expands the blast radius of any misconfiguration or compromise.
- **Lack of Human Oversight**: Directly patching live resources bypasses the normal software review pipeline (code review, CI, change management) that already governs infrastructure changes.
- **Infrastructure Drift**: When live resources are mutated without updating Terraform, configuration drift emerges, causing future `terraform apply` operations to undo fixes or introduce new risk.

TerraFix addresses these issues by operating exclusively at the Terraform layer. When an external compliance platform (Vanta) detects a failing test for a cloud resource, TerraFix:

1. Polls Vanta for the failure.
2. Clones the relevant Terraform repository.
3. Locates the Terraform resource corresponding to the failing ARN.
4. Uses Claude Sonnet 4.5 (via AWS Bedrock) to synthesize a compliant Terraform patch.
5. Opens a GitHub Pull Request (PR) for human review and approval.

The only permissions TerraFix requires are **read-only Vanta API access** and **GitHub PR creation**, avoiding direct AWS write access entirely. For future stakeholders (security engineers, SREs, platform teams, compliance officers), this design significantly reduces risk while still moving toward autonomous remediation.

### Team

This implementation is currently a **single-developer project** led by the author of TerraFix (Me). In terms of “roles,” I am simultaneously acting as:

- **Architect & Lead Engineer**: Responsible for overall system design, component decomposition, and high-level tradeoff decisions (e.g., SQLite vs. Redis, ECS vs. Lambda).
- **Backend Engineer**: Owns Python 3.14 implementation of Vanta integration, Terraform parsing, Bedrock prompt construction, GitHub integration, orchestration, and state management.
- **DevOps / SRE**: Owns Terraform-based infrastructure for ECS/Fargate, ECR, IAM, CloudWatch, and Secrets Manager, as well as Dockerization.
- **Researcher & Experiment Designer**: Designs the experiments that will evaluate TerraFix along throughput, resilience, and scalability dimensions (described below).

The current codebase is structured so that future contributors can take over specific components (e.g., adding new IaC backends or implementing the test harness) without needing to rewrite core logic.

### Experiments Overview

The experimental evaluation for TerraFix focuses on three major dimensions:

1. **Pipeline Throughput and Latency**  
   - Measure end-to-end latency from Vanta failure detection to GitHub PR creation.  
   - Quantify per-stage timings: repository cloning, Terraform parsing, Bedrock inference, PR creation.  
   - Characterize throughput under varying workloads (e.g., 1, 5, 10 concurrent failures).

2. **Concurrency and Failure Resilience**  
   - Evaluate behavior under realistic workload patterns: steady-state, bursty, and cascading failure scenarios.  
   - Inject controlled failures (Bedrock throttling, GitHub rate limiting, git timeouts) and measure retry-success rates, error recovery time, and queue depth stability.  
   - Verify deduplication logic under concurrent load to ensure only one PR is created per logical failure.

3. **Repository Analysis Scalability**  
   - Benchmark Terraform parsing and resource-matching performance across small, medium, and large repositories with increasing syntactic and semantic complexity.  
   - Track memory consumption and cache effectiveness.  
   - Evaluate prompt truncation strategies for large Terraform files and their impact on fix quality.

Current work has focused on **implementing the full pipeline and deployment architecture** so that these experiments can run against a realistic system rather than a toy prototype.

## Project Plan and Recent Progress

### High-Level Plan

The project plan, derived from the original specification, breaks the work into three phases:

1. **Core Components (Week 1)**  
   - Implement Vanta client, Terraform analyzer, Bedrock remediation generator, GitHub PR creator, and internal configuration/logging/error-handling layers.  
   - Establish a minimal orchestration loop and local SQLite-backed dedup store.

2. **Integration and Infrastructure (Week 2)**  
   - Integrate components into an end-to-end pipeline.  
   - Implement concurrent processing, state management, and robust retry semantics.  
   - Containerize the service and define ECS/Fargate infrastructure via Terraform.

3. **Experiments and Hardening (Week 3)**  
   - Design and implement the scalability experiments (throughput, resilience, parsing scalability).  
   - Instrument pipeline stages for detailed metrics.  
   - Prepare documentation, deployment guides, and operational runbooks.

The current implementation has essentially completed phases 1 and 2 at the code + infrastructure level, leaving the experimental harness and automated tests for future work.

### Detailed Task Breakdown and Timeline

Below is a summary of the work completed, aligned with the earlier three-week timeline:

- **Environment & Project Skeleton**  
  - Created Python 3.14 project structure under `src/terrafix`.  
  - Added `pyproject.toml`, `requirements.txt`, and `requirements-dev.txt` with explicit dependencies.  
  - Implemented robust `.gitignore` and `.dockerignore`.  
  - Wrote initial `README.md` describing architecture and local usage.

- **Vanta Integration**  
  - Implemented `VantaClient` with OAuth authentication, pagination, optional framework filtering, and enrichment logic.  
  - Defined a typed `Failure` model (`pydantic.BaseModel`) representing Vanta failures.  
  - Implemented deterministic failure hashing with SHA-256 for deduplication.  
  - Added error handling that wraps HTTP and network errors in `VantaApiError`.

- **Terraform Analysis**  
  - Implemented `TerraformAnalyzer` for recursive `.tf` discovery and HCL parsing via `python-hcl2`.  
  - Built mapping from AWS resource types (e.g., `AWS::S3::Bucket`) to Terraform resource types (e.g., `aws_s3_bucket`).  
  - Implemented ARN-based resource matching and module context extraction.  
  - Ensured parse failures are logged but non-fatal.

- **Bedrock Integration**  
  - Implemented `TerraformRemediationGenerator` with a Bedrock runtime client.  
  - Built detailed prompt templates with compliance failure context, Terraform configuration, and resource-specific documentation snippets.  
  - Implemented `_parse_response` to safely extract JSON from Claude’s output, validate required fields, and construct a `RemediationFix` model.  
  - Added explicit handling for Bedrock throttling and internal errors via `BedrockError` with `retryable` flags.

- **GitHub PR Creation**  
  - Implemented `GitHubPRCreator` using `PyGithub` for branch creation, file updates, and PR creation.  
  - Implemented conventional commit messages and a rich, Markdown PR body with a review checklist, confidence guidance, and current vs. required state views.  
  - Implemented label management, including on-the-fly label creation.  
  - Translated `GithubException` into `GitHubError` with rate limit metadata.

- **End-to-End Orchestration**  
  - Implemented `process_failure` in `orchestrator.py`, which coordinates dedup checks, repository cloning, Terraform analysis, Bedrock fix generation, and PR creation.  
  - Added retry logic with exponential backoff for Vanta, Bedrock, and GitHub transient errors.  
  - Implemented optional `terraform fmt` via subprocess, with safe fallback when unavailable.  
  - Ensured all steps are logged with correlation IDs and structured context.

- **Long-Running Service & CLI**  
  - Implemented `service.py` with a long-running polling loop, concurrent failure processing (`ThreadPoolExecutor`), and graceful shutdown on SIGTERM/SIGINT.  
  - Implemented `cli.py` providing `process-once`, `stats`, and `cleanup` commands for manual testing and operations.  
  - Implemented `StateStore` with a SQLite schema for processed failures, including cleanup and statistics APIs.

- **Docker & Terraform Infrastructure**  
  - Built a minimal, secure Docker image (Python 3.14, non-root user, git, terraform).  
  - Authored Terraform modules for ECR, ECS/Fargate, Secrets Manager, IAM roles, CloudWatch log groups and alarms, and networking variables.  
  - Wired environment variables and secrets into the ECS task definition, including SQLite state path and polling interval.  
  - Documented the deployment process in `terraform/README.md` and `DEPLOYMENT_GUIDE.md`.

- **Documentation & Summary**  
  - Created `IMPLEMENTATION_SUMMARY.md` encapsulating the design, components, and limitations.  
  - Wrote `CONTRIBUTING.md` and `.env.example` for future contributors.

## Objectives

### Short-Term Objectives (Course Horizon)

1. **Robust MVP Implementation**  
   - Deliver a working TerraFix service capable of taking real Vanta failures and producing GitHub PRs for Terraform repositories.  
   - Ensure the pipeline is resilient to common external failures (network issues, timeouts, API errors) and logs sufficient context for debugging.

2. **Experiment Harness and Instrumentation**  
   - Implement the three experiments (throughput, resilience, scalability) using the existing architecture.  
   - Instrument each pipeline stage with timing and error metrics suitable for statistical analysis (P50/P95/P99).

3. **Qualitative Evaluation of Fix Quality**  
   - Collect a corpus of generated PRs across multiple failure types (S3, IAM, RDS, security groups).  
   - Qualitatively rate them on correctness, compliance coverage, and maintainability, ideally with feedback from domain experts.

4. **Documentation and Operational Readiness**  
   - Finalize deployment and operations documentation so that a third-party team can deploy TerraFix without direct assistance.  
   - Document known limitations and explicit guardrails (e.g., non-persistence of SQLite state).

### Long-Term Objectives (Beyond the Course)

1. **Persistent, Highly Available Deployment**  
   - Replace ephemeral SQLite with a persistent, multi-writer store (e.g., Redis or PostgreSQL) or EFS-mounted SQLite for cross-task persistence.  
   - Introduce multi-task ECS deployments for high availability and horizontal scalability.

2. **Multi-IaC and Multi-Cloud Support**  
   - Extend TerraFix to support CloudFormation, Pulumi, and CDK, each with their own parsers and fix-generation prompts.  
   - Support multi-cloud resources (AWS, GCP, Azure) and multi-account environments.

3. **Automated Validation and Testing of Fixes**  
   - Integrate `terraform plan` and `terraform validate` into the pipeline, potentially running in isolated environments.  
   - Generate and run Terratest or similar automated tests to catch regressions introduced by fixes.

4. **Active Learning from Human Feedback**  
   - Capture reviewer actions (edits, approvals, rejections) as feedback signals.  
   - Use this feedback for prompt tuning, few-shot examples, or RL-based ranking of alternative fixes.

5. **Policy Authoring and Custom Rules Engine**  
   - Allow security teams to define organization-specific policies (beyond Vanta’s built-in tests) and map them to Terraform-level constraints.  
   - Enable TerraFix to remediate both vendor-defined and custom policies with a unified workflow.

6. **Drift Detection and Continuous Compliance**  
   - Extend the system to detect drift between live infrastructure and Terraform state (e.g., via periodic `terraform plan` runs or cloud config scans).  
   - Automatically open PRs or issues when drift compromises compliance, closing the loop from detection to remediation.

## Related Work

### Commercial Tools

- **Delve**: A notable existing tool that directly mutates AWS resources to remediate security findings. Delve demonstrates that AI-driven remediation is technically feasible but also highlights the primary risks TerraFix is designed to avoid: broad AWS write access, lack of human review, and IaC drift. TerraFix differentiates itself by operating solely at the Terraform layer and enforcing PR-based human review.

- **AWS Config / Security Hub / GuardDuty**: Native AWS services that detect misconfigurations and threats. While they can trigger automated remediations via Lambda or SSM documents, these again act at the resource layer, not the IaC layer. TerraFix complements these by offering a “compliance PR” path rather than direct live mutation.

- **Checkov / Terraform Cloud Policy Sets**: These tools focus on detecting policy violations in Terraform code pre-deployment. TerraFix can be thought of as their “write path” counterpart: given a violation, it attempts to synthesize the appropriate fix.

### Research and Academic Context

While the project is primarily engineering-focused, it intersects with several research areas:

- **AI-Assisted Programming and Code Generation**: TerraFix uses Claude Sonnet 4.5 to generate Terraform patches. This aligns with ongoing work on LLM-based code writing, refactoring, and automated bug fixing.
- **Autonomous Agents and Human-in-the-Loop Systems**: The architecture intentionally keeps humans in the approval loop via GitHub PRs, reflecting current best practices in deploying AI agents in safety-critical environments.
- **Configuration Management and Infrastructure as Code**: Work on preventing and repairing configuration errors (e.g., misconfigured firewalls, IAM policies) informs how TerraFix identifies and fixes misconfigurations.

### Course Readings and Concepts (Hypothetical Mapping)

This report references topics such as:

- Reliability and resilience patterns (circuit breakers, retries, backoff) reflected in the error-handling design.  
- Metrics-driven experimentation for systems performance and scalability.  
- Security and compliance frameworks that inform required-state definitions.

TerraFix positions itself at the intersection of these ideas by providing a practical, deployable system that turns compliance detection into actionable, reviewable infrastructure changes.

## Methodology

### System Architecture

The architecture follows the diagram in `Architecture Diagram.png` and the spec:

- **Polling Worker / Webhook Endpoint** (`service.py`)  
  - Periodically polls Vanta for failing tests.  
  - Deduplicates failures via the state store before dispatching them to worker threads.

- **Terraform Parser** (`terraform_analyzer.py`)  
  - Clones the target GitHub repo.  
  - Parses `.tf` files and locates resources corresponding to failure ARNs.

- **Analysis Engine** (`orchestrator.py`)  
  - Builds rich context (current config, module-level metadata, failure details).  
  - Calls the remediation generator and validates outputs.  
  - Coordinates PR creation and state updates.

- **AWS Bedrock Claude Sonnet 4.5** (`remediation_generator.py`)  
  - Receives a structured prompt with failure details and Terraform configuration.  
  - Returns a structured JSON object describing the proposed fix.

- **GitHub PR Creator** (`github_pr_creator.py`)  
  - Creates branches, commits the updated Terraform file, and opens PRs with detailed explanations.

- **State Storage** (`state_store.py`)  
  - Stores failure hashes, statuses, PR URLs, and error messages in SQLite for deduplication and observability.

### Experimental Methodology

The experiments will use the implemented system as-is, with synthetic and real failures fed into Vanta (or mocked Vanta responses).

#### Experiment 1: Pipeline Throughput and Latency

**Objective**: Quantify how quickly TerraFix can turn detected failures into PRs, and identify bottlenecks.

**Method**:

- Construct a synthetic failure generator that emulates Vanta responses for different Terraform repositories (small, medium, large).  
- For each scenario (e.g., 1, 5, 10 concurrent failures), run the worker for a fixed duration.  
- Instrument and record per-stage timings:
  - `t_fetch`: Vanta API call  
  - `t_clone`: git clone  
  - `t_parse`: Terraform parsing and resource matching  
  - `t_bedrock`: Bedrock call (prompt construction + inference)  
  - `t_pr`: GitHub branch + commit + PR creation  
- Compute P50, P95, and P99 latency for each stage and end-to-end.

**Evaluation Criteria**:

- Maximum sustainable throughput (failures per minute) on a single worker.  
- Identification of the dominant bottleneck (expected: Bedrock and git operations).  
- Evidence that retries do not explode latency under moderate error rates.

#### Experiment 2: Concurrency and Failure Resilience

**Objective**: Evaluate how TerraFix behaves under bursty workloads and external failures, focusing on error recovery and deduplication.

**Method**:

- Define workload patterns:
  - **Steady-state**: 1–3 failures every few minutes.  
  - **Burst**: 15–20 failures within 60 seconds.  
  - **Cascade**: Multiple failures referencing related resources in the same repo.  
- Inject controlled failures:
  - Simulate Bedrock throttling via test credentials or mocks that return throttling errors.  
  - Simulate GitHub rate limiting and intermittent failures.  
  - Introduce git clone timeouts via network shaping or mocks.  
- Measure:
  - Retry-success rate (how many transient errors are eventually resolved).  
  - Error recovery time (time from failure onset to return to normal throughput).  
  - Queue depth over time and evidence of stability.  
  - Deduplication correctness (only one PR per logical failure).

**Evaluation Criteria**:

- Retry-success rate > 95% for transient errors.  
- Stable queue depth without unbounded growth.  
- No duplicate PRs for identical failures, even under concurrent processing.

#### Experiment 3: Repository Analysis Scalability

**Objective**: Understand how Terraform parsing and resource matching scale with repository size and complexity.

**Method**:

- Construct a corpus of Terraform repositories:
  - **Small**: 5–15 resources, limited modules.  
  - **Medium**: 50–100 resources, moderate module usage.  
  - **Large**: 300+ resources, deep module nesting and complex dependencies.  
- For each repo, measure:
  - `t_parse_total`: total time to parse all `.tf` files.  
  - `t_match`: time to locate a resource by ARN.  
  - Peak memory usage during parsing and matching.  
- Evaluate the effectiveness of any caching strategies (if later added) by measuring warm vs. cold parsing performance.

**Evaluation Criteria**:

- Parsing and matching times remain acceptable for large repos (e.g., < 30 seconds for P95).  
- Memory usage remains within the constraints of the chosen ECS task size.  
- Identify any structural factors (e.g., module depth) that significantly impact performance.

## Preliminary Results

At this stage, the focus has been on **building the system and deployment architecture**, not on running the experiments. This is because I completely redid the entire project from scratch from an older/worse version of the idea that was too similar to Delve, and did not have time to run the experiments or write proper tests.

However, several important preliminary outcomes exist:

1. **Functional Integration**  
   - All core components (Vanta client, Terraform analyzer, Bedrock generator, GitHub PR creator, state store, orchestrator, service loop) are implemented, type-annotated, and documented.  
   - The orchestration flow matches the architecture diagram: Vanta → Terraform Analyzer → Analysis Engine → Bedrock → GitHub PR → SQLite state store.

2. **Deployment Readiness**  
   - A Docker image and Terraform infrastructure are defined and documented, enabling repeatable deployment to ECS/Fargate.  
   - Secrets, IAM roles, logging, and networking are wired correctly at the IaC layer.

3. **Qualitative Pipeline Validity**  
   - The prompt design, fix representation, and PR templates reflect best practices from the spec and should yield meaningful, reviewable PRs once real failures are fed into the system.

### What Remains for Final Results

To complete the evaluation:

- Implement the synthetic failure generator and Vanta response mocks required for controlled experiments.  
- Add detailed timing instrumentation around all pipeline stages, emitting structured metrics to logs (or a metrics endpoint) for later analysis.  
- Run the three experiments across multiple repository sizes and workloads.  
- Collect and visualize results (e.g., latency distributions, throughput curves, error recovery timelines).  
- Perform qualitative analysis of a sample of generated PRs to assess correctness and compliance coverage.

## Impact

TerraFix has the potential to significantly reshape how organizations enforce and remediate infrastructure compliance:

- **Reduced Blast Radius**: By working only at the Terraform layer and never directly mutating live resources, TerraFix dramatically reduces the risk associated with automated remediation tools. Stakeholders can continue to rely on existing CI/CD and code review practices as the primary control plane.

- **Operational Efficiency**: Security and compliance teams often spend substantial time opening Jira tickets and manually crafting Terraform patches. TerraFix automates the tedious parts of that workflow, allowing humans to focus on review and policy decisions rather than mechanical edits.

- **Stronger Governance and Auditability**: Every change flows through GitHub PRs with rich context, explicit checklists, and detailed explanations. This produces an auditable history of compliance remediations (who approved what, when, and why) that integrates cleanly with existing governance processes.

- **Scalable Compliance for Growing Cloud Footprints**: As organizations scale to hundreds of accounts and thousands of resources, manual remediations do not scale. TerraFix aims to support high throughput while keeping humans in the approval loop, enabling teams to meet compliance obligations without exploding headcount.

- **Template for Safe AI Agents in Operations**: Beyond compliance, TerraFix serves as a pattern for designing AI agents that operate on source-of-truth artifacts (code, IaC) instead of live systems. This pattern—“AI writes the patch, humans approve and deploy”—is likely to be reused across many operational domains.

If the planned experiments confirm that TerraFix can process failures with acceptable latency, handle bursts gracefully, and scale to large repositories, the system could provide a concrete, deployable blueprint for AI-driven, human-in-the-loop compliance remediation in production environments. Stakeholders—including security engineers, SREs, platform teams, and auditors—would gain a tool that increases compliance posture without sacrificing safety, transparency, or control.
